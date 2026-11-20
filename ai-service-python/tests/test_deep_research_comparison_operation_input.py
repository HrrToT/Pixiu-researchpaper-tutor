from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_intent import operations_enabled,synthesis_input_limit
from services.deep_research.method_navigation import bundle,priority
from services.deep_research.synthesis_evidence import order_premises,fit_premises
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
from test_deep_research_comparison_intent import record
from test_deep_research_method_navigation import evidence


@pytest.mark.parametrize('version,expected',[(None,24000),(True,24000),(0,24000),(1,24000),(2,32000),(3,24000)])
def test_only_frozen_comparison_v2_selects_operation_input_window(version,expected):
    r=record();r['comparisonPlanningContractVersion']=version
    before=deepcopy(r)
    assert synthesis_input_limit(r)==expected
    assert operations_enabled(r) is (expected==32000)
    assert r==before
    r['state']['outputKind']='experiment_design';assert synthesis_input_limit(r)==24000


def test_method_steps_are_prioritized_over_benchmark_setup_without_altering_sources():
    q='说明压缩流程所需的额外处理步骤与优化开销。'
    setup=evidence('For fair comparison we retrained two baselines on our GPU.',0)
    method=evidence('We prune redundant elements and recover the representation by fine-tuning.',1)
    follow=evidence('We distill coefficients and quantize their attributes into a codebook.',2)
    rows=[setup,method,follow];before=deepcopy(rows)
    assert priority(method,q,'compression pipeline','identification',operations=True)>priority(setup,q,'compression pipeline','identification',operations=True)
    selected=bundle(rows,q,'compression pipeline','identification',operations=True)
    assert method in selected and follow in selected and setup not in selected
    assert rows==before


def test_operation_policy_cannot_reclassify_a_literal_related_work_request():
    row=evidence('We prune redundant elements and distill coefficients.',1)
    assert not bundle([row],'解释相关工作中的压缩机制','compression mechanism','explanation',operations=True)


def test_operation_bundles_keep_own_versions_and_complete_context_before_optional_tables():
    q='说明压缩流程各步骤及其作用。'
    method=evidence('We distill coefficients and quantize the attributes.',1)
    method['sourceContext']='We first prune redundant elements. '+method['quote']+' The remaining state is recovered.'
    foreign=evidence('We distill coefficients and quantize the attributes.',2,source='foreign')
    table=evidence('Table caption: Quantitative comparisons. Size FPS 2.0 3.0 4.0 5.0 6.0.',3)
    table['tableData']={'groups':[],'rows':[]}
    rows=[table,foreign,method];before=deepcopy(rows)
    plan=[{'obligations':[{'obligationId':'o','question':q,'requiredSources':['owned'],
      'searchQuery':'compression pipeline','comparisonRole':{'kind':'per_paper'},
      'completionCriteria':[{'criterionId':'c','requirement':q,'responseType':'explanation'}]}]}]
    selected,groups=order_premises(rows,plan,comparison_operations=True)
    assert groups[0]['navigationRole']=='comparison_operation'
    assert method['evidenceId'] in groups[0]['evidenceIds']
    assert all(foreign['evidenceId'] not in g['evidenceIds'] for g in groups)
    assert groups[0]['requiredContextByEvidenceId'][method['evidenceId']]['before']
    _,visible,missing=fit_premises(selected,lambda v:str(v),groups,max_bytes=32000,
        required_contexts={eid:c for g in groups for eid,c in g.get('requiredContextByEvidenceId',{}).items()})
    assert not missing and next(e for e in visible if e['evidenceId']==method['evidenceId'])['sourceContextRequired']
    assert rows==before


@pytest.mark.parametrize('version,configured,expected',[(1,32000,24000),(2,None,24000),(2,16000,16000),(2,32000,32000)])
def test_tracker_source_window_obeys_server_configuration_and_preserves_other_nodes(version,configured,expected):
    r=record();r['comparisonPlanningContractVersion']=version
    tracker=TrackedLLMInvoker(Mock(),Mock(),Mock(),run_record_fn=lambda rid:r,
                              experiment_max_input_bytes=configured)
    assert tracker.prompt_byte_limit('r','synthesize')==expected
    assert tracker.prompt_byte_limit('r','resolve_brief')==24000


@pytest.mark.parametrize('error',[BudgetExhaustedError('tokens',100000,100001),DeepResearchError('unresolved_unknown','Existing unknown')])
def test_larger_source_window_does_not_bypass_atomic_budget_or_resend_unknown(error):
    r=record();r['comparisonPlanningContractVersion']=2
    client=Mock();reserve=Mock(side_effect=error);complete=Mock()
    tracker=TrackedLLMInvoker(client,reserve,complete,run_record_fn=lambda rid:r,experiment_max_input_bytes=32000)
    with pytest.raises(type(error)) as caught:
        tracker('r','synthesize','x'*30000,{'max_tokens':4000},use_reserve=True)
    assert caught.value is error and reserve.call_count==1
    assert reserve.call_args.kwargs['budget_delta']=={'modelCalls':1,'tokens':35024}
    client.invoke.assert_not_called();complete.assert_not_called()


def test_oversized_window_still_rejects_before_reservation():
    r=record();r['comparisonPlanningContractVersion']=2
    client=Mock();reserve=Mock()
    tracker=TrackedLLMInvoker(client,reserve,Mock(),run_record_fn=lambda rid:r,experiment_max_input_bytes=32000)
    with pytest.raises(ValueError,match='Prompt too large'):
        tracker('r','synthesize','x'*32001,{'max_tokens':4000},use_reserve=True)
    reserve.assert_not_called();client.invoke.assert_not_called()
