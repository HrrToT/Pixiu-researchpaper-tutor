from concurrent.futures import ThreadPoolExecutor

import pytest

from services.deep_research.contracts import BudgetExhaustedError, UnresolvedUnknownError
from services.deep_research.repository import DeepResearchRepository


def setup(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / 'reserve.sqlite3'))
    repo.initialize()
    repo.create_run({'runId': 'r', 'budget': {'maxTokens': 100, 'reserveTokens': 40}})
    repo.begin_execution('r')
    return repo


def reserve(repo, key, tokens, final=False):
    return repo.reserve_call(run_id='r', node='verify' if final else 'extract', tool='fixture',
        args_digest=key, budget_delta={'tokens': tokens, 'normalTokens': 999}, use_reserve=final)[0]


def test_normal_calls_cannot_spend_closing_tokens_and_refunds_stay_in_pool(tmp_path):
    repo = setup(tmp_path)
    normal = reserve(repo, 'normal', 60)
    with pytest.raises(BudgetExhaustedError):
        reserve(repo, 'blocked', 1)
    final = reserve(repo, 'final', 40, True)
    repo.complete_call(normal['callId'], status='succeeded', budget_delta={'tokens': -20, 'normalTokens': -999})
    repo.complete_call(final['callId'], status='succeeded', budget_delta={'tokens': -10, 'normalTokens': -999})
    budget = repo.require_run('r')['budget']
    assert (budget['tokens'], budget['normalTokens']) == (70, 40)
    reserve(repo, 'next', 20)
    with pytest.raises(BudgetExhaustedError):
        reserve(repo, 'still-blocked', 1)
    assert len(repo.list_calls('r')) == 3


def test_parallel_reservations_are_atomic_and_unknown_keeps_token_pool(tmp_path):
    repo = setup(tmp_path)
    def attempt(key):
        try:
            return reserve(repo, key, 40)
        except BudgetExhaustedError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [c for c in pool.map(attempt, ['a', 'b']) if c]
    assert len(calls) == 1
    repo.complete_call(calls[0]['callId'], status='unknown')
    assert repo.require_run('r')['budget']['normalTokens'] == 40
    with pytest.raises(UnresolvedUnknownError):
        reserve(repo, 'cannot-reissue', 1, True)


def test_small_profile_keeps_a_proportional_reserve(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / 'small.sqlite3'))
    repo.initialize()
    record, _ = repo.create_run({'runId': 'small', 'budget': {'maxTokens': 1000}})
    assert record['budget']['reserveTokens'] == 500
