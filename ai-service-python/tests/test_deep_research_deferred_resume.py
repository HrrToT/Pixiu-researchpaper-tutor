"""Accepted human input survives unavailable execution slots without blind dispatch."""
from concurrent.futures import Future
from copy import deepcopy

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.facade import ResearchFacade, _compute_allowed_actions
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_clarification_context import ClarificationModel, wait_worker


@pytest.mark.parametrize('reason', ['execution_capacity', 'execution_busy'])
def test_saved_clarification_defers_then_resumes_same_checkpoint_only_on_new_human_action(tmp_path, reason):
    repo = DeepResearchRepository(tmp_path / 'research.sqlite3')
    repo.initialize()
    model = ClarificationModel()
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=model,
                            scope_validator=lambda *_: True, max_concurrent=1)
    blocker = Future()
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'start',
            'question': '研究质量和速度，300字以内。', 'materials': [{'materialId': 'p'}]}, start_async=True)
        rid = run['runId']
        waiting = wait_worker(facade, repo, rid, 'waiting_user')
        frozen = deepcopy((waiting['materials'], waiting['sourcePolicy'], waiting['budget']))
        before_epoch = waiting['executionEpoch']
        facade._active_futures[rid if reason == 'execution_busy' else 'other'] = blocker
        payload = {'requestId': 'clarify-1', 'expectedRunRevision': waiting['runRevision'],
                   'answer': '只看画质，给初学者解释，200字以内。'}
        deferred = facade.action(rid, 'clarify', payload)
        assert deferred['status'] == 'waiting_user' and deferred['clarification'] is None
        assert deferred['resumeDeferred']['reason'] == reason
        assert set(deferred['allowedActions']) == {'resume', 'cancel'}
        assert deferred['executionEpoch'] == before_epoch and len(model.prompts) == 1
        after = repo.require_run(rid)
        assert after['state']['clarificationHistory'] == [{
            'question': waiting['state']['clarificationQuestion'], 'answer': payload['answer']}]
        assert (after['materials'], after['sourcePolicy'], after['budget']) == frozen
        # Availability changing never starts the run on its own. Replaying the
        # accepted clarify action still returns its saved receipt.
        blocker.set_result(None)
        assert facade.action(rid, 'clarify', payload) == deferred
        assert facade.get(rid)['runRevision'] == deferred['runRevision']
        assert len(model.prompts) == 1
        resumed_payload = {'requestId': 'resume-1', 'expectedRunRevision': deferred['runRevision']}
        response = facade.action(rid, 'resume', resumed_payload)
        waiting_again = wait_worker(facade, repo, rid, 'waiting_user')
        assert waiting_again['executionEpoch'] == before_epoch + 1
        assert len(model.prompts) == 2  # Only the new clarified brief, not the old request.
        assert 'resumeDeferred' not in waiting_again['state']
        assert len(waiting_again['state']['clarificationHistory']) == 1
        assert set(facade.get(rid)['allowedActions']) == {'clarify', 'cancel'}
        assert facade.action(rid, 'resume', resumed_payload) == response
        assert len(model.prompts) == 2 and len(repo.list_calls(rid)) == 2
    finally:
        if not blocker.done():
            blocker.set_result(None)
        facade.shutdown()


def test_repeated_busy_resume_has_a_new_revision_but_replayed_action_never_dispatches(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object(), max_concurrent=1)
    blocker = Future()
    facade._active_futures['other'] = blocker
    repo.create_run({'runId': 'r', 'taskId': 't'})
    try:
        first = {'requestId': 'resume-1', 'expectedRunRevision': repo.require_run('r')['runRevision']}
        deferred = facade.action('r', 'resume', first)
        assert deferred['status'] == 'queued' and deferred['resumeDeferred']
        assert not repo.require_run('r').get('startedAt')
        assert facade.action('r', 'resume', first) == deferred
        second = {'requestId': 'resume-2', 'expectedRunRevision': deferred['runRevision']}
        again = facade.action('r', 'resume', second)
        assert again['runRevision'] > deferred['runRevision']
        assert again['executionEpoch'] == deferred['executionEpoch'] == 0
        assert not repo.list_calls('r')
        assert set(facade._active_futures) == {'other'}
    finally:
        blocker.set_result(None)
        facade.shutdown()


@pytest.mark.parametrize('state,actions', [
    ({'clarificationNeeded': True, 'clarification': 'old'}, {'clarify', 'cancel'}),
    ({'clarificationNeeded': False, 'clarification': ''}, {'clarify', 'cancel'}),
    ({'clarificationNeeded': False, 'clarification': 'human answer'}, {'resume', 'cancel'}),
])
def test_only_a_saved_answer_exposes_resume_instead_of_another_clarification_form(state, actions):
    assert set(_compute_allowed_actions({'status': 'waiting_user', 'state': state})) == actions


def test_unrelated_resume_error_is_not_mislabeled_as_a_deferred_success(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't'})
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    def reject():
        raise DeepResearchError('not_capacity', 'Other failure')
    facade._require_capacity = reject
    try:
        revision = repo.require_run('r')['runRevision']
        with pytest.raises(DeepResearchError, match='Other failure'):
            facade.action('r', 'resume', {'requestId': 'resume', 'expectedRunRevision': revision})
        assert repo.require_run('r')['runRevision'] == revision
        assert 'resumeDeferred' not in repo.require_run('r')['state']
        assert not repo.list_calls('r')
    finally:
        facade.shutdown()
