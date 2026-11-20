from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.method_intent import query_intent,operation_score
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.verification import make_evidence
from services.deep_research.membership_candidates import named_membership_candidates
from services.deep_research.data_availability import validate_data_availability
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.repair import repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_experiment_intent import inputs as repair_inputs


def evidence():
    return [{'evidenceId':key,'sourceWorkId':'p','sourceVersionId':'v2','accessLevel':'fulltext',
             'quote':quote,'verification':{'literal':'passed'}} for key,quote in (
        ('parent','We evaluate the D-NeRF dataset.'),
        ('member','We observed a discrepancy in the Lego in D-NeRF dataset.'))]


def data_claim():
    return {'claimId':'d','kind':'proposal','designRole':'data','designContractVersion':2,
        'text':'拟用同一场景。','evidenceRefs':['parent','member'],
        'executionSpec':{'dataset':'D-NeRF','scenes':{'mode':'named','names':['Lego']}}}


def test_source_operation_and_staged_training_outrank_benefit_claims_only_in_new_policy():
    overview='We jointly train and initialize the method in two stages.'
    stages='We train initially for a fixed number of iterations. Subsequently we jointly train the model.'
    assert operation_score(overview,'Method','training')>operation_score(stages,'Implementation Details','training')
    assert operation_score(overview,'Method','training',operational=True)<operation_score(stages,'Implementation Details','training',operational=True)
    operation='We add Gaussian noise to the encoded time input with a linearly decaying schedule. Equation: x = f(t + noise).'
    benefit='Our smoothing mechanism improves quality and reduces jitter.'
    assert query_intent('annealing smoothing training mechanism') is None
    assert query_intent('annealing smoothing training mechanism',operational=True)=='operation'
    assert operation_score(operation,'Technique','operation',operational=True)>operation_score(benefit,'Introduction','operation',operational=True)
    assert operation_score(operation,'Related Work','operation',operational=True)==0


def test_bounded_extraction_gets_actual_operation_and_named_member_before_overviews():
    texts=[('intro','Introduction','Our method improves quality on a benchmark dataset.'),
        ('operation','Technique','We add Gaussian noise to encoded time, and decay it over training iterations. Equation: x = f(t + noise).'),
        ('member','Results','We observed a discrepancy in the Lego in D-NeRF dataset.')]
    obs={'method':{'obligationId':'method','question':'检验退火平滑是否有帮助','searchQuery':'smoothing training mechanism','requiredSources':['p']},
         'data':{'obligationId':'data','question':'核对数据集及实际成员','searchQuery':'dataset subset scene membership','requiredSources':['p']}}
    sources=[{'sourceId':key,'workId':'p','versionId':'v2','contentHash':'a'*64,'accessLevel':'fulltext',
        'obligationIds':list(obs),'pages':[{'page':1,'section':section,'text':text}]} for key,section,text in texts]
    pending=[(s,s['pages'][0],s['pages'][0]['text']) for s in sources];before=deepcopy(pending)
    ordered=prioritize_extraction_passages(pending,obs,6)
    assert [r[0]['sourceId'] for r in ordered[:2]]==['operation','member'] and pending==before
    record={'extractionPriorityVersion':6,'adaptiveExtractionContractVersion':1,
            'state':{'readResults':sources,'evidence':[],'plan':[{'obligations':list(obs.values())}]}}
    def update(_rid,change,**_):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    sent=[]
    def invoke(_rid,node,prompt,_options):
        sent.append(prompt);rows=json.JSONDecoder().raw_decode(prompt[prompt.index('[{"sourceId"'):])[0]
        assert node=='extract' and 'ACTUAL operation' in prompt and len(rows)<=3
        return {'content':json.dumps([{'sourceId':r['sourceId'],'passageId':r['passageId'],
            'quote':r['text'],'obligationIds':list(obs),'conditions':{}} for r in rows])}
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert len(sent)==1 and [e['sourceId'] for e in record['state']['evidence']][:2]==['operation','member']
    assert all(e['verification']['literal']=='passed' for e in record['state']['evidence'])


def test_named_candidates_select_the_own_member_quote_and_never_retarget_a_verdict():
    claim=data_claim();ev=evidence();before=deepcopy((claim,ev))
    candidates=named_membership_candidates([claim],ev)
    assert candidates=={'d':[{'evidenceId':'member','nameBindings':[{'selectedName':'Lego','sourceLabel':'Lego'}]}]}
    wrong={'dataAvailability':{'evidenceId':'parent','quote':ev[0]['quote'],'scopeQuote':'D-NeRF dataset','availableNames':['Lego']}}
    assert validate_data_availability(claim,wrong,ev)==['DA_NAME_NOT_IN_QUOTE']
    assert (claim,ev)==before and wrong['dataAvailability']['evidenceId']=='parent'


@pytest.mark.parametrize('change',['foreign','abstract','unchecked','substring'])
def test_candidates_cannot_expand_own_permission_or_weaken_literal_names(change):
    claim=data_claim();ev=evidence()
    if change=='foreign':claim['evidenceRefs']=['parent']
    elif change=='abstract':ev[1]['accessLevel']='abstract'
    elif change=='unchecked':ev[1]['verification']['literal']='unchecked'
    else:ev[1]['quote']='We evaluate LegoCity in D-NeRF dataset.'
    assert named_membership_candidates([claim],ev)=={'d':[]}


def test_case_variant_is_explicit_and_a_negated_member_still_needs_semantic_review():
    claim=data_claim();claim['executionSpec']['scenes']['names']=['lego'];ev=evidence()
    assert named_membership_candidates([claim],ev)['d'][0]['nameBindings']==[{'selectedName':'lego','sourceLabel':'Lego'}]
    ev[1]['quote']='The Lego scene is NOT included in the D-NeRF dataset.'
    assert named_membership_candidates([claim],ev)['d']  # Lexical, never scientific approval.
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'d','status':'failed','reason':'The source excludes this member.'}])})
    result=BudgetedSemanticChecker(invoke,'r',experiment_intent_review=3)([claim],ev)
    assert result[0]['status']=='failed'
    prompt=invoke.call_args.kwargs['prompt'];view=json.JSONDecoder().raw_decode(prompt.split('Evidence:\n',1)[1])[0]
    assert view['literalNameCandidatesNotMembershipProof']['d'][0]['evidenceId']=='E2'
    assert view['evidence']['E1']['quote']==ev[0]['quote']


def test_paper_intervention_without_own_fulltext_fails_without_a_provider_call():
    group={'claimId':'g','kind':'proposal','designRole':'groups','text':'启用论文所述方法，拟议权重为0.1。',
           'evidenceRefs':[],'executionSpec':{}}
    invoke=Mock(side_effect=AssertionError('No unsupported method dispatch'))
    result=BudgetedSemanticChecker(invoke,'r',experiment_intent_review=3)([group],evidence())
    assert result[0]['status']=='failed' and '自身' in result[0]['reason']
    invoke.assert_not_called()


def test_source_attributed_group_gets_scientific_review_and_old_policy_keeps_its_request_role():
    group={'claimId':'g','kind':'proposal','designRole':'groups','text':'启用论文所述方法。','evidenceRefs':['member'],'executionSpec':{}}
    calls=[]
    def invoke(**kwargs):
        calls.append(kwargs);return {'content':json.dumps([{'claimId':'g','status':'failed','reason':'Wrong operation.'}])}
    BudgetedSemanticChecker(invoke,'r',experiment_intent_review=3)([group],evidence())
    assert calls[-1]['node']=='verify_design_science' and 'actual operation, input/state and schedule' in calls[-1]['prompt']
    BudgetedSemanticChecker(invoke,'r',experiment_intent_review=2)([group],evidence())
    assert calls[-1]['node']=='verify_design_config'


def test_testing_an_authors_claim_does_not_turn_a_new_proposed_operation_into_a_paper_method():
    group={'claimId':'g','kind':'proposal','designRole':'groups','text':'拟议两个新操作进行对照。',
           'evidenceRefs':[],'executionSpec':{}}
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'g','status':'failed','reason':'Fixture scientific failure.'}])})
    result=BudgetedSemanticChecker(invoke,'r',research_question='设计实验检验作者的观点',experiment_intent_review=3)([group],[])
    assert invoke.call_count==1 and invoke.call_args.kwargs['node']=='verify_design_science'
    assert result[0]['reason']=='Fixture scientific failure.'


def test_pending_scientific_repair2_cannot_be_retargeted_to_method_policy3():
    report,verification,ev=repair_inputs();states=[]
    def unknown(_):raise OSError('unknown')
    with pytest.raises(OSError):
        repair_rejected(report,verification,ev,'描述性比较',unknown,json.loads,
            experimental_intent=2,checkpoint=states.append)
    no_send=Mock()
    with pytest.raises(DeepResearchError):
        repair_rejected(report,verification,ev,'描述性比较',no_send,json.loads,
            experimental_intent=3,batch_state=states[-1])
    no_send.assert_not_called()
