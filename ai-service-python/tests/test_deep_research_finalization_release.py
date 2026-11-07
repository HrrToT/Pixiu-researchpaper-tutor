from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from services.deep_research.contracts import (
    BudgetExhaustedError, CallOutsideRunningError, UnresolvedUnknownError, check_budget_limits)
from services.deep_research.finalization_pool import prepare_finalization_budget, select_reservation_pool
from services.deep_research.final_coverage import coverage_prompt_byte_limit
from services.deep_research.repository import DeepResearchRepository


def budget(**overrides):
    value = {'maxTokens': 100000, 'tokens': 62860, 'normalTokens': 26622, 'reserveTokens': 50000,
        'maxModelCalls': 18, 'modelCalls': 7, 'reserveModelCalls': 5, 'reservedModelCalls': 5,
        'maxWallClockSeconds': 360, 'elapsedSeconds': 114,
        'finalizationBudgetVersion': 1, 'releasedReserveTokens': 0}
    value.update(overrides)
    return value


def repository(tmp_path, value=None):
    repo = DeepResearchRepository(str(tmp_path / 'research.sqlite3'))
    repo.initialize()
    repo.create_run({'runId': 'run', 'status': 'running', 'budget': value or budget()})
    return repo


def reserve(repo, identity='audit', cost=30000, node='verify_answer_coverage', protected=True):
    return repo.reserve_call(run_id='run', node=node, tool='llm_invoke', args_digest=identity,
        budget_delta={'modelCalls': 1, 'tokens': cost}, use_reserve=protected)


def test_actual_failed_case_capacity_becomes_available_without_changing_any_limit_or_usage():
    value = budget()
    before = deepcopy(value)
    proposed = prepare_finalization_budget(value, {'modelCalls': 1, 'tokens': 30000}, True, 'verify_answer_coverage')
    assert proposed['releasedReserveTokens'] == 13762
    assert {k: v for k, v in proposed.items() if k != 'releasedReserveTokens'} == {
        k: v for k, v in value.items() if k != 'releasedReserveTokens'}
    assert select_reservation_pool(value, {'modelCalls': 1, 'tokens': 30000}, True, 'verify_answer_coverage') is False
    assert coverage_prompt_byte_limit(value, 5882) == 24000
    assert value == before


def test_repository_atomically_releases_records_and_settles_the_actual_normal_call(tmp_path):
    repo = repository(tmp_path)
    call, reused = reserve(repo)
    assert not reused and call['usesReserve'] is False and call['reservedTokens'] == 30000
    current = repo.require_run('run')['budget']
    assert current['releasedReserveTokens'] == 13762
    assert current['normalTokens'] == 56622 and current['tokens'] == 92860
    assert current['modelCalls'] == 8 and current['reservedModelCalls'] == 5
    assert current['maxTokens'] == 100000 and current['reserveTokens'] == 50000
    assert check_budget_limits(current) is None
    with pytest.raises(ValueError, match='Unexpected call status'):
        reserve(repo)
    assert repo.require_run('run')['budget'] == current
    repo.complete_call(call['callId'], status='succeeded', reservation_token=call['reservationToken'],
        result={'content': 'saved'}, budget_delta={'tokens': -22000, 'releasedReserveTokens': 50000})
    settled = repo.require_run('run')['budget']
    assert settled['tokens'] == 70860 and settled['normalTokens'] == 34622
    assert settled['releasedReserveTokens'] == 13762  # Caller cannot alter the transfer.
    same, reused = reserve(repo)
    assert reused and same['callId'] == call['callId']
    assert repo.require_run('run')['budget'] == settled
    restarted = DeepResearchRepository(repo.db_path)
    assert restarted.require_run('run')['budget'] == settled


@pytest.mark.parametrize('change', ['legacy', 'forged_version', 'bad_transfer', 'unspent_call_slots',
    'nonfinal_node', 'not_requested', 'total_cost_exceeded', 'total_calls_exhausted'])
def test_release_cannot_bypass_scope_or_existing_limits(change):
    value, delta, requested, node = budget(), {'modelCalls': 1, 'tokens': 30000}, True, 'verify_answer_coverage'
    if change == 'legacy': value.pop('finalizationBudgetVersion')
    elif change == 'forged_version': value['finalizationBudgetVersion'] = True
    elif change == 'bad_transfer': value['releasedReserveTokens'] = 50001
    elif change == 'unspent_call_slots': value['reservedModelCalls'] = 4
    elif change == 'nonfinal_node': node = 'extract'
    elif change == 'not_requested': requested = False
    elif change == 'total_cost_exceeded': delta['tokens'] = 40000
    elif change == 'total_calls_exhausted': value['modelCalls'] = 13
    original = deepcopy(value)
    assert prepare_finalization_budget(value, delta, requested, node) == original
    assert value == original


@pytest.mark.parametrize('node', ['extract', 'assess_relevance', 'repair_claims', 'invented_node'])
def test_exploration_and_unapproved_nodes_cannot_spend_previously_released_tokens(tmp_path, node):
    repo = repository(tmp_path, budget(releasedReserveTokens=13762))
    before = repo.require_run('run')
    with pytest.raises(BudgetExhaustedError):
        reserve(repo, cost=30000, node=node)
    assert repo.require_run('run') == before and repo.list_calls('run') == []


def test_over_total_reservation_rolls_back_the_transfer_and_leaves_no_call(tmp_path):
    repo = repository(tmp_path)
    before = repo.require_run('run')
    with pytest.raises(BudgetExhaustedError):
        reserve(repo, cost=40000)
    assert repo.require_run('run') == before and not repo.list_calls('run')


def test_concurrent_final_reservations_never_double_spend_the_same_total_balance(tmp_path):
    repo = repository(tmp_path)
    def worker(index):
        try:
            other = DeepResearchRepository(repo.db_path)
            reserve(other, identity=str(index), cost=20000)
            return True
        except BudgetExhaustedError:
            return False
    with ThreadPoolExecutor(max_workers=4) as workers:
        result = list(workers.map(worker, range(4)))
    assert sum(result) == 1 and len(repo.list_calls('run')) == 1
    assert repo.require_run('run')['budget']['tokens'] == 82860


def test_unknown_call_still_blocks_new_work_before_any_transfer(tmp_path):
    repo = repository(tmp_path)
    previous, _ = reserve(repo, identity='previous', cost=10, node='resolve_brief', protected=False)
    repo.complete_call(previous['callId'], status='unknown', reservation_token=previous['reservationToken'],
                       error={'code': 'unknown'})
    before = repo.require_run('run')
    with pytest.raises(UnresolvedUnknownError):
        reserve(repo)
    assert repo.require_run('run') == before and len(repo.list_calls('run')) == 1


def test_legacy_budget_keeps_its_original_partition_and_is_not_migrated(tmp_path):
    value = budget()
    value.pop('finalizationBudgetVersion')
    value.pop('releasedReserveTokens')
    repo = repository(tmp_path, value)
    before = repo.require_run('run')
    with pytest.raises(BudgetExhaustedError):
        reserve(repo)
    assert repo.require_run('run') == before and not repo.list_calls('run')


def test_batch_overflow_does_not_release_tokens_while_a_protected_slot_remains():
    value = budget(reservedModelCalls=4)
    assert prepare_finalization_budget(value, {'modelCalls': 2, 'tokens': 30000},
                                       True, 'verify_answer_coverage') == value


@pytest.mark.parametrize('status', ['paused', 'completed', 'failed', 'cancelled'])
def test_nonrunning_status_still_blocks_before_release(tmp_path, status):
    repo = repository(tmp_path)
    repo.update_run('run', lambda run: {**run, 'status': status})
    before = repo.require_run('run')
    with pytest.raises(CallOutsideRunningError):
        reserve(repo)
    assert repo.require_run('run') == before and not repo.list_calls('run')


def test_wall_deadline_still_blocks_before_release(tmp_path):
    repo = repository(tmp_path)
    repo.update_run('run', lambda run: {**run, 'startedAt': '2000-01-01T00:00:00+00:00'})
    before = repo.require_run('run')
    with pytest.raises(BudgetExhaustedError) as caught:
        reserve(repo)
    assert caught.value.details['kind'] == 'elapsedSeconds'
    assert repo.require_run('run') == before and not repo.list_calls('run')


def test_client_cannot_disable_or_initialize_the_server_owned_release(tmp_path):
    from services.deep_research.facade import ResearchFacade
    repo = repository(tmp_path)
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object())
    try:
        record, created = facade.create({'workspaceTaskId': 'task', 'operationKey': 'create',
            'question': 'Explain', 'materials': [], 'finalizationBudgetVersion': 0,
            'releasedReserveTokens': 50000, 'budget': {
                'finalizationBudgetVersion': 0, 'releasedReserveTokens': 50000}}, start_async=False)
        assert created
        stored = repo.require_run(record['runId'])['budget']
        assert stored['finalizationBudgetVersion'] == 1 and stored['releasedReserveTokens'] == 0
    finally:
        facade.shutdown()
