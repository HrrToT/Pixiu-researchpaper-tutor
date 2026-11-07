from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.review_batches import plan


def test_finds_two_complete_requests_when_midpoint_needs_three():
    claims = [{'claimId': str(i)} for i in range(5)]
    before = deepcopy(claims)
    feasible = {frozenset({'0', '2', '4'}), frozenset({'1', '3'})}
    calls = []
    def preview(rows):
        ids = frozenset(c['claimId'] for c in rows)
        calls.append(ids)
        return {'inputBytes': 5 if ids in feasible or len(ids) == 1 else 20, 'maxInputBytes': 10}
    result = plan(claims, preview)
    assert {frozenset(c['claimId'] for c in group) for group in result} == feasible
    assert len(calls) == len(set(calls)) <= 31
    assert claims == before


def test_equal_call_counts_choose_fewer_complete_input_bytes():
    claims = [{'claimId': str(i)} for i in range(3)]
    def preview(rows):
        ids = {c['claimId'] for c in rows}
        size = 20 if len(ids) == 3 else 3 if ids == {'0', '2'} else 5
        return {'inputBytes': size, 'maxInputBytes': 10}
    result = plan(claims, preview)
    assert [set(c['claimId'] for c in group) for group in result] == [{'0', '2'}, {'1'}]


def test_unsplittable_target_does_not_drop_it_or_send_an_incomplete_request():
    claims = [{'claimId': 'a'}, {'claimId': 'b'}]
    assert plan(claims, lambda rows: {'inputBytes': 20, 'maxInputBytes': 10}) is None


@pytest.mark.parametrize('claims', [[], [{'claimId': 'a'}], [{'claimId': 'a'}] * 2,
                                       [{'claimId': str(i)} for i in range(9)]])
def test_unbounded_or_ambiguous_inputs_use_existing_path_without_preview(claims):
    preview = Mock()
    assert plan(claims, preview) is None
    preview.assert_not_called()


@pytest.mark.parametrize('value', [True, -1, '9', None])
def test_invalid_size_cannot_authorize_a_request(value):
    with pytest.raises(ValueError):
        plan([{'claimId': 'a'}, {'claimId': 'b'}],
             lambda _: {'inputBytes': value, 'maxInputBytes': 10})


def test_exact_prospective_preview_never_dispatches_or_mutates_inputs():
    import json
    from services.deep_research.tools import BudgetedSemanticChecker
    from test_deep_research_review_envelope import Capture, args
    k = args('data')
    claims = json.loads(k['claims_text'])
    before = deepcopy((claims, k['context']))
    capture = Capture()
    checker = BudgetedSemanticChecker(capture, 'offline', prospective_review=3,
                                       prospective_envelope=10, review_batch_planning=1)
    preview = checker._check_batch(claims, [], k['context'], node='verify_design_config', _preview=True)
    assert preview['inputBytes'] > 0 and preview['maxInputBytes'] == 32000
    assert not capture.sent
    assert (claims, k['context']) == before


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_planner_contract_is_server_owned_and_immutable(tmp_path, replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'runs.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        row, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Experiment',
                                'deferStart': True, 'reviewBatchPlanningContractVersion': replacement}, start_async=False)
        assert row['reviewBatchPlanningContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(row['runId'], lambda r: {**r, 'reviewBatchPlanningContractVersion': replacement})
    finally:
        facade.shutdown()
