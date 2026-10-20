from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.experiment_template import enabled
from services.deep_research.graph import make_synthesize_node
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_synthesis_premises import evidence


def record():
    return {'question':'只比较一个操作的开关，设计单场景描述性实验。',
        'experimentDraftContractVersion':1,'experimentIntentContractVersion':3,
        'synthesisEvidenceContractVersion':1,'protocolContractVersion':2,
        'workflowContractVersion':4,'budgetContractVersion':1,'hypothesisContractVersion':1,
        'state':{'outputKind':'experiment_design','evidence':[
            evidence('eq','We define the operation as h = f(x, t + n), where n is annealed noise.')],
            'plan':[{'obligations':[{'obligationId':'o','question':'操作实现是什么',
                'requiredSources':['p'],'completionCriteria':[{'criterionId':'operation',
                    'requirement':'操作的定义公式及作用位置','responseType':'explanation'}]}]}]}}


def synthesize(original):
    current=deepcopy(original)
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    invoke=Mock(return_value={'finishReason':'length'})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    return result,current,invoke


def test_shared_grammar_keeps_original_operation_and_complete_configuration_before_call():
    original=record();before=deepcopy(original)
    _,current,invoke=synthesize(original)
    prompt=invoke.call_args.args[2]
    assert len(prompt.encode())<=24000
    assert original['state']['evidence'][0]['quote'] in prompt
    assert not current['state']['synthesisPremiseAllocation']['missingPremiseBundles']
    # Shared initialization, paired budgets, real motion and leakage safeguards
    # must remain available together with the actual defining source operation.
    for requirement in ['baselineInitialization','stateDefinitions','componentInitializations',
                        'group_checkpoints','paired_cluster_bootstrap','interval_excludes_zero',
                        'workflowClaimId','including control','Final evaluation views cannot choose checkpoints',
                        'insertion point','real\nscene/camera motion','reconstruction-quality guard']:
        assert requirement in prompt
    assert original==before


def test_missing_required_source_premise_stops_before_a_paid_draft_instead_of_silently_dropping_it():
    original=record()
    # A whole original source quote cannot fit; no source clipping or increased cap.
    original['state']['evidence'][0]['quote']='We define the operation as '+('indivisible original source '*1200)
    result,current,invoke=synthesize(original)
    assert result=={'error_code':'synthesis_evidence_capacity'}
    invoke.assert_not_called()
    assert current['state']['synthesisPremiseAllocation']['missingPremiseBundles']
    assert current['state']['evidence']==original['state']['evidence']


@pytest.mark.parametrize('field,value', [('experimentDraftContractVersion',True),
    ('experimentDraftContractVersion',None),('workflowContractVersion',3),('protocolContractVersion',1)])
def test_old_or_incompatible_schema_never_uses_new_experiment_generation_view(field,value):
    old=record();old[field]=value
    assert not enabled(old)
    _,_,invoke=synthesize(old)
    assert 'Shared executionSpec grammar.' not in invoke.call_args.args[2]


@pytest.mark.parametrize('replacement',[None,True,'1',0,4])
def test_compact_experiment_contract_is_server_owned_and_frozen(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        payload,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'设计实验',
            'experimentDraftContractVersion':replacement,'deferStart':True},start_async=False)
        assert payload['experimentDraftContractVersion']==3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(payload['runId'],lambda r:{**r,'experimentDraftContractVersion':replacement})
    finally:
        facade.shutdown()
