from copy import deepcopy
import json

import pytest

from services.deep_research.comparison_reasoning import enabled,audit_scope,validate_audit,GUIDANCE
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import make_evidence,verify_claims
from services.deep_research.verification_aliases import restore_verdict_evidence


def inputs(right_device='Device X'):
    evidence=[]
    for work,device in [('first','Device X'),('second',right_device)]:
        quote=f'We evaluate our results on {device}.'
        evidence.append(make_evidence({'workId':work,'versionId':'v1','contentHash':work+'-hash','accessLevel':'fulltext'},
                         quote,quote,location={'page':1},obligation_ids=['o']))
    claim={'claimId':'c','kind':'inference','text':'这些原文还不足以确认跨论文比较的全部条件已对齐。',
           'evidenceRefs':[e['evidenceId'] for e in evidence],'conditions':{},'obligationIds':['o']}
    return claim,evidence


def audit(evidence,alignment='not_established',differences=None,scope='cross_study'):
    return {'scope':scope,'alignment':alignment,'supportsClaim':True,
            'premises':[{'evidenceId':e['evidenceId'],'quote':e['quote']} for e in evidence],
            'differences':differences or []}


def check(claim,evidence,extra=None,*,new=True,status='passed'):
    sent=[]
    def invoke(**kwargs):
        sent.append(kwargs)
        verdict={'claimId':claim['claimId'],'status':status,'reason':'Fixture judgement'}
        if extra is not None:
            wire=deepcopy(extra)
            reverse={e['evidenceId']:f'E{i+1}' for i,e in enumerate(evidence)}
            wire=restore_verdict_evidence({'comparisonAudit':wire},reverse)['comparisonAudit']
            verdict['comparisonAudit']=wire
        return {'content':json.dumps([verdict])}
    result=BudgetedSemanticChecker(invoke,'r',comparison_reasoning=new)([claim],evidence)
    return result[0],sent


def difference(evidence,left_value='Device X',right_value='Device Y'):
    return {'dimension':'hardware',
            'left':{'evidenceId':evidence[0]['evidenceId'],'quote':evidence[0]['quote'],'value':left_value},
            'right':{'evidenceId':evidence[1]['evidenceId'],'quote':evidence[1]['quote'],'value':right_value}}


def test_plain_passed_verdict_is_not_enough_for_new_cross_source_inference_but_legacy_request_stays_unchanged():
    c,e=inputs()
    legacy,old=check(c,e,new=False)
    current,new=check(c,e)
    assert legacy['status']=='passed' and current['status']=='failed'
    assert 'comparisonAudit' not in old[0]['prompt'] and 'comparisonAudit' in new[0]['prompt']
    assert old[0]['extra_body']==new[0]['extra_body']=={'max_tokens':4000,'temperature':0.0}
    assert old[0]['use_reserve'] is True and new[0]['use_reserve'] is True
    assert 'comparison_premise_not_established' in current['reason']


def test_unknown_alignment_can_support_a_bounded_inference_without_fabricating_differences():
    c,e=inputs();before=deepcopy((c,e))
    result,sent=check(c,e,audit(e))
    assert result['status']=='passed' and result['comparisonAudit']['premises'][0]['evidenceId']==e[0]['evidenceId']
    assert (c,e)==before and GUIDANCE in sent[0]['prompt']
    assert all(x['quote'] in sent[0]['prompt'] for x in e)
    assert 'same reported experiment' in sent[0]['prompt']


def test_identical_bound_values_cannot_be_declared_a_demonstrated_difference():
    c,e=inputs()
    a=audit(e,'different',[difference(e,right_value='Device X')])
    result,_=check(c,e,a)
    assert result['status']=='failed' and 'comparison_values_not_different' in result['reason']


def test_two_quoted_distinct_values_still_need_an_independent_semantic_pass():
    c,e=inputs('Device Y');a=audit(e,'different',[difference(e)])
    passed,_=check(c,e,a)
    failed,_=check(c,e,a,status='failed')
    assert passed['status']=='passed' and failed['status']=='failed'
    assert not verify_claims([c],e)['accepted']
    assert verify_claims([c],e,lambda *_:[passed])['accepted']


@pytest.mark.parametrize('mutation',[
    'no_audit','wrong_scope','string_true','missing_source','foreign_quote','foreign_id',
    'unknown_with_difference','difference_missing','value_not_in_quote','difference_same_source','wrong_quote_case',
    'malformed_id','empty_premise',
])
def test_invalid_comparison_premises_cannot_close_a_claim(mutation):
    c,e=inputs('Device Y');a=audit(e)
    if mutation=='no_audit': a=None
    elif mutation=='wrong_scope': a['scope']='within_study'
    elif mutation=='string_true': a['supportsClaim']='true'
    elif mutation=='missing_source': a['premises']=a['premises'][:1]
    elif mutation=='foreign_quote': a['premises'][0]['quote']='A different condition is established.'
    elif mutation=='foreign_id': a['premises'][0]['evidenceId']='foreign'
    elif mutation=='unknown_with_difference': a['differences']=[difference(e)]
    elif mutation=='difference_missing': a['alignment']='different'
    elif mutation=='value_not_in_quote': a.update(alignment='different',differences=[difference(e,left_value='Device Z')])
    elif mutation=='difference_same_source':
        pair=difference(e);pair['right']['evidenceId']=pair['left']['evidenceId'];pair['right']['quote']=pair['left']['quote'];pair['right']['value']='results'
        a.update(alignment='different',differences=[pair])
    elif mutation=='wrong_quote_case': a['premises'][0]['quote']=a['premises'][0]['quote'].lower()
    elif mutation=='malformed_id': a['premises'][0]['evidenceId']=['foreign']
    else: a['premises']=[]
    result,_=check(c,e,a)
    assert result['status']=='failed'


def test_audit_uses_work_and_version_identity_not_title_or_source_count():
    c,e=inputs()
    e[1]['sourceWorkId']=e[0]['sourceWorkId'];e[1]['sourceVersionId']='v2'
    assert audit_scope(c,e)=='cross_study'
    assert not validate_audit(c,{'comparisonAudit':audit(e)},e)
    incomplete=audit(e);incomplete['premises']=incomplete['premises'][:1]
    assert validate_audit(c,{'comparisonAudit':incomplete},e)==['comparison_source_premise_missing']
    e[1]['sourceVersionId']='v1'
    assert audit_scope(c,e) is None


def test_two_table_rows_from_one_work_have_a_separate_bounded_audit():
    quote='Table row 1: Baseline | 20\nTable row 2: Ours | 30'
    ev=make_evidence({'workId':'paper','versionId':'v1','contentHash':'hash','accessLevel':'fulltext'},
                     quote,quote,location={'table':'t1'},obligation_ids=['o'])
    ev['tableData']={'groups':[['Dataset A',['FPS']]],'rows':[[1,'Baseline',['20']],[2,'Ours',['30']]]}
    claim={'claimId':'c','kind':'reported','text':'Dataset A 的Baseline：FPS20；Ours：FPS30。',
           'evidenceRefs':[ev['evidenceId']],'tableBindings':[
                {'evidenceId':ev['evidenceId'],'rowNumber':n,'groupIndex':0,'metric':'FPS','value':v} for n,v in [(1,'20'),(2,'30')]]}
    assert audit_scope(claim,[ev])=='within_study'
    result,_=check(claim,[ev],audit([ev],alignment='established',scope='within_study'))
    assert result['status']=='passed'
    assert verify_claims([claim],[ev],lambda *_:[result])['accepted']
    wrong={**claim,'text':claim['text'].replace('FPS30','FPS99')}
    assert not verify_claims([wrong],[ev],lambda *_:[result])['accepted']


def test_new_policy_does_not_add_audit_or_calls_to_a_single_source_noncomparative_fact():
    c,e=inputs();c['evidenceRefs']=c['evidenceRefs'][:1]
    result,sent=check(c,e)
    assert result['status']=='passed' and len(sent)==1 and 'comparisonAudit' not in sent[0]['prompt']
    assert audit_scope({**c,'tableBindings':None},e) is None
    assert audit_scope({**c,'kind':'proposal'},e) is None


@pytest.mark.parametrize('version',[None,False,True,0,'1',5])
def test_server_contract_version_is_strict(version):
    assert not enabled({'comparisonReasoningContractVersion':version})
    assert enabled({'comparisonReasoningContractVersion':1})


@pytest.mark.parametrize('changed',[None,True,0,2])
def test_comparison_contract_cannot_change_after_creation(tmp_path,changed):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize()
    repo.create_run({'runId':'r','comparisonReasoningContractVersion':1})
    with pytest.raises(ValueError,match='Immutable run field'):
        repo.update_run('r',lambda r:{**r,'comparisonReasoningContractVersion':changed})


def test_client_cannot_disable_contract_and_runtime_checker_uses_frozen_server_version(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'one','question':'比较实验条件','materials':[],
                          'comparisonReasoningContractVersion':0},start_async=False)
        assert repo.require_run(p['runId'])['comparisonReasoningContractVersion']==4
        checker=facade._build_semantic_checker(p['runId'],lambda **_:None)
        assert checker._comparison_reasoning() is True
    finally:
        facade.shutdown()


def test_unknown_repair_request_cannot_be_retargeted_to_the_new_comparison_policy():
    from services.deep_research.repair import repair_rejected
    from services.deep_research.contracts import DeepResearchError
    c,e=inputs();report={'claims':[c]};failed={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]};states=[]
    def unknown(*_): raise OSError('Unknown transport')
    with pytest.raises(OSError):
        repair_rejected(report,failed,e,'比较实验条件',unknown,json.loads,checkpoint=states.append,comparison_reasoning=True)
    with pytest.raises(DeepResearchError):
        repair_rejected(report,failed,e,'比较实验条件',lambda *_:pytest.fail('No retarget'),json.loads,
                         batch_state=states[-1],comparison_reasoning=False)
