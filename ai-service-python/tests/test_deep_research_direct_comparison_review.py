from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, UnknownCallError
from services.deep_research.factual_review import DIRECT_REVIEW_OPTION, OPTION
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker


def record(profile=3):
    return {'comparisonAuthoringContractVersion': profile,
            'comparisonPlanningContractVersion': 6, 'comparisonReviewBatchContractVersion': 2,
            'state': {'outputKind': 'paper_comparison'}}


def test_direct_review_reserves_the_actual_bounded_output_before_dispatch():
    reserve = Mock(return_value=({'result': {'content': '[]'}}, True))
    provider = Mock()
    invoke = TrackedLLMInvoker(provider, reserve, Mock(), run_record_fn=lambda _: record())
    invoke('r', 'verify', 'Unchanged full evidence', {DIRECT_REVIEW_OPTION: True, 'max_tokens': 4000})
    assert reserve.call_args.kwargs['budget_delta'] == {
        'modelCalls': 1, 'tokens': len('Unchanged full evidence') + 1024 + 4000}
    provider.invoke.assert_not_called()
    options = research_model_options('verify', {DIRECT_REVIEW_OPTION: True, 'max_tokens': 4000})
    assert options == {'max_tokens': 4000, 'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none'}
    assert research_model_options('verify', {OPTION: True})['max_tokens'] == 8192


@pytest.mark.parametrize('profile', [None, True, '3', 0, 1, 2])
def test_direct_review_cannot_change_old_or_unmarked_runs(profile):
    reserve, provider = Mock(), Mock()
    invoke = TrackedLLMInvoker(provider, reserve, Mock(), run_record_fn=lambda _: record(profile))
    with pytest.raises(DeepResearchError, match='初审直答'):
        invoke('r', 'verify', 'source', {DIRECT_REVIEW_OPTION: True})
    reserve.assert_not_called()
    provider.invoke.assert_not_called()


@pytest.mark.parametrize('options', [
    {DIRECT_REVIEW_OPTION: 'yes'}, {DIRECT_REVIEW_OPTION: True, OPTION: True},
    {DIRECT_REVIEW_OPTION: True, 'max_tokens': True},
    {DIRECT_REVIEW_OPTION: True, 'max_tokens': 4001},
])
def test_invalid_profiles_are_rejected(options):
    with pytest.raises(ValueError):
        research_model_options('verify', options)


def test_direct_review_retains_unknown_request_protection():
    reserve = Mock(side_effect=UnknownCallError('uncertain'))
    provider = Mock()
    invoke = TrackedLLMInvoker(provider, reserve, Mock(), run_record_fn=lambda _: record())
    with pytest.raises(UnknownCallError):
        invoke('r', 'verify', 'source', {DIRECT_REVIEW_OPTION: True})
    assert reserve.call_count == 1
    provider.invoke.assert_not_called()


def test_direct_review_keeps_existing_time_admission():
    from test_deep_research_bounded_factual_review import cell_record
    r = {**cell_record(), **record()}
    r['budget']['elapsedSeconds'] = 357
    reserve, provider = Mock(), Mock()
    invoke = TrackedLLMInvoker(provider, reserve, Mock(), run_record_fn=lambda _: r)
    assert invoke('r', 'verify', 'source', {DIRECT_REVIEW_OPTION: True})['notStarted'] == 'factual_review_time_budget'
    reserve.assert_not_called()
    provider.invoke.assert_not_called()


def test_direct_review_preserves_whole_claim_decoding_and_own_source_gates():
    import json
    from services.deep_research.tools import BudgetedSemanticChecker
    from test_deep_research_comparison_review_batches import inputs, response
    claims, evidence = inputs()
    rows = [response(c['claimId'], i) for i, c in enumerate(claims)]
    rows[1]['scopeAudit']['premises'][0]['evidenceId'] = 'E1'
    old = Mock(return_value={'content': json.dumps(rows)})
    new = Mock(return_value={'content': json.dumps(rows)})
    def checker(invoke, direct):
        return BudgetedSemanticChecker(invoke, 'r', single_factual_decision=True,
            factual_scope=True, complete_factual_scope=True, isolate_factual_claims=True,
            audit_source_fields=True, audit_target_fields=True, scope_source_paths=True,
            comparison_review_batches=True, bounded_factual_review=True,
            direct_comparison_review=direct)
    assert checker(old, False)(claims, evidence) == checker(new, True)(claims, evidence)
    assert old.call_args.kwargs['prompt'] == new.call_args.kwargs['prompt']
    assert old.call_args.kwargs['extra_body'][OPTION] is True
    assert new.call_args.kwargs['extra_body'][DIRECT_REVIEW_OPTION] is True
    assert OPTION not in new.call_args.kwargs['extra_body']


def test_saved_v15_pressure_admits_bounded_next_request_without_larger_budget(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'pressure.sqlite3')
    repo.initialize()
    r = {**record(), 'runId': 'r', 'status': 'running', 'budget': {
        'maxModelCalls': 18, 'reserveModelCalls': 5, 'maxTokens': 100000,
        'reserveTokens': 50000, 'modelCalls': 6, 'reservedModelCalls': 5,
        'tokens': 68398, 'normalTokens': 20384}}
    repo.create_run(r)
    call, reused = repo.reserve_call(run_id='r', node='verify', tool='llm_invoke',
        args_digest='bounded-review-pressure', budget_delta={'modelCalls': 1, 'tokens': 27744},
        use_reserve=True)
    assert not reused
    budget = repo.require_run('r')['budget']
    assert budget['maxTokens'] == 100000 and budget['maxModelCalls'] == 18
    assert budget['tokens'] == 96142
    assert budget['reservedModelCalls'] == 5 and budget['modelCalls'] == 7
    assert call['status'] == 'pending'
