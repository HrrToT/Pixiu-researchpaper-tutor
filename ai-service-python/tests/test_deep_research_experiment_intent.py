from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.experiment_intent import guidance,enabled,single_toggle_request
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.contracts import DeepResearchError
from services.deep_research.comparison_methodology import REFERENCE


def inputs():
    report={'claims':[{'claimId':'h','kind':'hypothesis','designRole':'hypothesis',
        'text':'未执行的单场景描述性配对实验。','evidenceRefs':['e'],'conditions':{},'obligationIds':['o'],
        'executionSpec':{'purpose':'explore','analysisRef':'a','effectKeys':['delta'],'statement':'较低的抖动测量值'}},
        {'claimId':'a','kind':'proposal','designRole':'analysis','text':'按配对观测报告差值。','evidenceRefs':[],
         'conditions':{},'executionSpec':{'decision':{'mode':'descriptive'},'seed':2026}}]}
    verification={'accepted':[{'claimId':'fixed','kind':'proposal','text':'共用初始化，训练上限1000步。',
        'designRole':'budget','executionSpec':{'baseline':{'maxBudget':1000}}}],
        'rejected':[{'claimId':'h','reason':'semantic_unresolved','detail':'测量定义不足'}]}
    evidence=[{'evidenceId':'e','sourceWorkId':'p','sourceVersionId':'v2','accessLevel':'fulltext',
        'verification':{'literal':'passed'},'quote':'The method adds annealed noise during training.',
        'sourceContext':'The method adds annealed noise during training. This is our operation.',
        'obligationIds':['o']}]
    return report,verification,evidence


def test_compact_prospective_repair_retains_targets_sources_and_all_consistency_definitions():
    report,verification,evidence=inputs();before=deepcopy((report,verification,evidence))
    kwargs=dict(draft_context=[report['claims'][1]],comparison_methodology=True,max_prompt_bytes=24000)
    old=_prepare_repair(report,verification,evidence,'只作描述性抖动比较',**kwargs)
    new=_prepare_repair(report,verification,evidence,'只作描述性抖动比较',experimental_intent=True,**kwargs)
    assert old['originals']==new['originals'] and old['allowed']==new['allowed'] and old['aliases']==new['aliases']
    assert REFERENCE in old['prompt'] and REFERENCE not in new['prompt']
    assert evidence[0]['quote'] in new['prompt'] and '1000' in new['prompt'] and '2026' in new['prompt']
    assert 'Accepted experimental definitions' in new['prompt'] and 'UNVERIFIED consistency context' in new['prompt']
    assert 'standard deviation of per-frame PSNR scores ALONE' in new['prompt']
    assert len(new['prompt'].encode())<len(old['prompt'].encode())<=24000
    assert (report,verification,evidence)==before


def test_new_experiment_policy_does_not_remove_cross_paper_logic_from_factual_repair():
    report,verification,evidence=inputs();report['claims'][0].update(kind='inference')
    old=_prepare_repair(report,verification,evidence,'比较条件',comparison_methodology=True)
    new=_prepare_repair(report,verification,evidence,'比较条件',comparison_methodology=True,experimental_intent=True)
    assert old==new and REFERENCE in new['prompt']


def test_semantic_review_respects_descriptive_intent_without_approving_an_invalid_metric():
    report,_,evidence=inputs();calls=[]
    def invoke(**kwargs):
        calls.append(kwargs)
        return {'content':json.dumps([{'claimId':'h','status':'failed','reason':'Score variance alone is not jitter.'}])}
    checker=BudgetedSemanticChecker(invoke,'r',research_question='只作单场景描述性抖动比较',experiment_intent_review=True)
    verdict=checker([report['claims'][0]],evidence)
    assert verdict[0]['status']=='failed'
    assert 'The user explicitly requests DESCRIPTIVE comparison' in calls[0]['prompt']
    assert 'NO significance test' in calls[0]['prompt'] and 'quality guard' in calls[0]['prompt']
    assert 'ground truth at unobserved interpolation times' in calls[0]['prompt']


def test_unknown_legacy_experiment_request_is_not_retargeted_to_new_template():
    report,verification,evidence=inputs();states=[]
    def unknown(_):raise OSError('unknown')
    with pytest.raises(OSError):
        repair_rejected(report,verification,evidence,'描述性比较',unknown,json.loads,checkpoint=states.append)
    dispatch=Mock()
    with pytest.raises(DeepResearchError,match='不一致'):
        repair_rejected(report,verification,evidence,'描述性比较',dispatch,json.loads,
            batch_state=states[-1],experimental_intent=True)
    dispatch.assert_not_called()


def test_experiment_policy_is_server_owned_and_frozen(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'设计实验',
            'experimentIntentContractVersion':0},start_async=False)
        assert enabled(r) and r['experimentIntentContractVersion']==3
        for value in [True,0,None,1,2]:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(r['runId'],lambda old:{**old,'experimentIntentContractVersion':value})
    finally:facade.shutdown()


def test_v2_shared_definitions_are_checked_without_requiring_repeated_thresholds():
    report,_,evidence=inputs();invoke=Mock(return_value={'content':json.dumps([
        {'claimId':'h','status':'failed','reason':'No concrete metric anywhere.'}])})
    checker=BudgetedSemanticChecker(invoke,'r',research_question='描述性抖动比较',experiment_intent_review=2)
    assert checker([report['claims'][0]],evidence)[0]['status']=='failed'
    prompt=invoke.call_args.kwargs['prompt']
    assert 'need not be copied into every hypothesis/limits paragraph' in prompt
    old=Mock(return_value={'content':json.dumps([
        {'claimId':'h','status':'failed','reason':'No concrete metric anywhere.'}])})
    BudgetedSemanticChecker(old,'r',experiment_intent_review=True)([report['claims'][0]],evidence)
    assert 'need not be copied' not in old.call_args.kwargs['prompt']


def test_pending_v1_experiment_cannot_be_retargeted_to_coupled_v2():
    report,verification,evidence=inputs();states=[]
    def unknown(_):raise OSError('unknown')
    with pytest.raises(OSError):
        repair_rejected(report,verification,evidence,'描述性比较',unknown,json.loads,
            experimental_intent=True,checkpoint=states.append)
    no_send=Mock()
    with pytest.raises(DeepResearchError):
        repair_rejected(report,verification,evidence,'描述性比较',no_send,json.loads,
            experimental_intent=2,batch_state=states[-1])
    no_send.assert_not_called()


def test_unrelated_factorial_reference_is_only_omitted_for_an_explicit_single_toggle_request():
    assert single_toggle_request('同一场景两组：关闭平滑与启用论文所述平滑')
    assert not single_toggle_request('设计两因素四组实验，检验交互作用')
    assert not single_toggle_request('两组：关闭剪枝、量化与启用二者')
    assert not single_toggle_request('比较几种方法')


def test_experiment_does_not_dispatch_when_no_acquired_premise_fits():
    from services.deep_research.graph import make_synthesize_node
    record={'experimentIntentContractVersion':1,'protocolContractVersion':2,'workflowContractVersion':4,
        'budgetContractVersion':1,'hypothesisContractVersion':1,'question':'只作描述性的单场景实验',
        'state':{'outputKind':'experiment_design','evidence':[{'evidenceId':'e','quote':'Q'*30000,
        'sourceWorkId':'p','sourceVersionId':'v1','accessLevel':'fulltext','obligationIds':['o']}],
        'plan':[{'obligations':[{'obligationId':'o','question':'设计对照','requiredSources':['p']}]}]}}
    invoke=Mock();before=deepcopy(record)
    result=make_synthesize_node(invoke,lambda *_a,**_k:record)({'run_id':'r'})
    assert result['error_code']=='synthesis_evidence_capacity' and record==before
    invoke.assert_not_called()


def test_compact_latest_experiment_draft_preserves_method_evidence_and_all_typed_states():
    from services.deep_research.graph import make_synthesize_node
    texts=['Dataset Example contains scene Sample.']+['Background detail. '*20 for _ in range(8)]
    method='We estimate motion from the previous frame, then add residual components for newly observed regions.'
    texts.append(method)
    evidence=[{'evidenceId':'e'+str(i),'sourceWorkId':'p','sourceVersionId':'v1','accessLevel':'fulltext',
               'quote':text,'sourceContext':'Our method. '+text,'obligationIds':['o']} for i,text in enumerate(texts)]
    record={'experimentIntentContractVersion':1,'protocolContractVersion':2,'workflowContractVersion':4,
        'budgetContractVersion':1,'hypothesisContractVersion':1,'question':'单因素两组，只作单场景描述性比较。',
        'state':{'outputKind':'experiment_design','evidence':evidence,'metricDomains':['quality'],
        'plan':[{'obligations':[{'obligationId':'o','question':'设计对照','requiredSources':['p']}]}]}}
    invoke=Mock(return_value={'finishReason':'length'});before=deepcopy(record)
    make_synthesize_node(invoke,lambda *_a,**_k:record)({'run_id':'r'})
    prompt=invoke.call_args.args[2]
    rows=json.JSONDecoder().raw_decode(prompt.split('Evidence summaries:\n',1)[1])[0]
    assert method in [r['quote'] for r in rows] and texts[0] in [r['quote'] for r in rows]
    assert 'baselineInitialization' in prompt and 'stateDefinitions' in prompt
    assert 'Workflow contract 4' in prompt and 'Explicit descriptive comparison' in prompt
    assert 'Statistical reference (only for two binary factors)' not in prompt
    assert len(prompt.encode())<=24000 and record==before
