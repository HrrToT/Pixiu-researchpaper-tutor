"""Plan revisions cross the API boundary, without widening source policy."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository


def plan(source='paper', question='核查报告的条件'):
    return [{'itemId': 'i', 'question': question, 'searchQuery': 'old query', 'obligations': [
        {'obligationId': 'o', 'question': question, 'searchQuery': 'old query', 'requiredSources': [source],
         'completionCriteria': [{'criterionId': 'conditions', 'requirement': '说明报告的适用条件',
                                 'responseType': 'limitation'}]}]}]


@pytest.fixture
def setup_run(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't', 'materials': [{'materialId': 'paper'}],
        'sourcePolicy': {'mode': 'task_only'}, 'planEditContractVersion': 1, 'planCompletionContractVersion': 1,
        'state': {'plan': plan(), 'planRevision': 2}})
    repo.begin_execution('r')
    paused = repo.transition('r', 'paused')
    facade = ResearchFacade(repo, lambda **_: None, llm_client=Mock(), scope_validator=lambda *_: True)
    yield repo, facade, paused
    facade.shutdown()


@pytest.mark.parametrize('value', [None, True, '2', -1, 2.0])
def test_missing_or_malformed_revision_never_changes_the_plan(setup_run, value):
    repo, facade, before = setup_run
    payload = {'plan': plan()}
    if value is not None:
        payload['planRevision'] = value
    with pytest.raises(DeepResearchError) as caught:
        facade._action_plan('r', before['runRevision'], payload)
    assert caught.value.code == 'invalid_plan_revision'
    assert repo.require_run('r') == before and not repo.list_calls('r')


def test_stale_plan_revision_rejected_even_when_run_revision_is_current(setup_run):
    repo, facade, before = setup_run
    with pytest.raises(DeepResearchError) as caught:
        facade._action_plan('r', before['runRevision'], {'plan': plan(), 'planRevision': 1})
    assert caught.value.code == 'plan_revision_conflict'
    assert caught.value.details['status_code'] == 409
    assert repo.require_run('r') == before


def test_plan_action_keeps_payload_unchanged_and_duplicate_action_returns_saved_result(setup_run):
    repo, facade, before = setup_run
    payload = {'requestId': 'edit', 'expectedRunRevision': before['runRevision'],
               'planRevision': 2, 'plan': plan(question='核查新的条件')}
    original = deepcopy(payload)
    result = facade.action('r', 'plan', payload)
    assert payload == original
    assert result['planRevision'] == 3
    assert 'searchQuery' not in result['plan'][0]
    assert 'searchQuery' not in result['plan'][0]['obligations'][0]
    assert facade.action('r', 'plan', payload) == result
    assert repo.require_run('r')['runRevision'] == result['runRevision']
    assert not repo.list_calls('r')


@pytest.mark.parametrize('policy', ['academic_external', 'external_only'])
@pytest.mark.parametrize('identity', ['arxiv:2308.04079', 'arxiv:2308.04079v1', 'arxiv:astro-ph/0612345v2'])
def test_valid_public_identity_retained_under_existing_external_policy(setup_run, policy, identity):
    repo, facade, _ = setup_run
    before = repo.update_run('r', lambda r: {**r, 'sourcePolicy': {'mode': policy}})
    result = facade._action_plan('r', before['runRevision'], {'planRevision': 2, 'plan': plan(source=identity)})
    assert result['plan'][0]['obligations'][0]['requiredSources'] == [identity]
    assert repo.require_run('r')['sourcePolicy'] == {'mode': policy}
    assert repo.require_run('r')['materials'] == before['materials']
    assert repo.require_run('r')['budget'] == before['budget']
    assert not repo.list_calls('r')


@pytest.mark.parametrize('identity', ['foreign', 'https://arxiv.org/abs/2308.04079', 'arxiv:../../secret',
                                     'arxiv:127.0.0.1', 'arxiv:2308.04079?token=secret'])
def test_noncanonical_or_foreign_source_rejected_before_any_call(setup_run, identity):
    repo, facade, _ = setup_run
    before = repo.update_run('r', lambda r: {**r, 'sourcePolicy': {'mode': 'academic_external'}})
    with pytest.raises(DeepResearchError, match='材料范围'):
        facade._action_plan('r', before['runRevision'], {'planRevision': 2, 'plan': plan(source=identity)})
    assert repo.require_run('r') == before and not repo.list_calls('r')


def test_task_only_edit_cannot_add_an_external_identity_even_if_payload_asks_for_it(setup_run):
    repo, facade, before = setup_run
    with pytest.raises(DeepResearchError, match='材料范围'):
        facade._action_plan('r', before['runRevision'], {'planRevision': 2,
            'sourcePolicy': {'mode': 'academic_external'}, 'plan': plan(source='arxiv:2308.04079v1')})
    assert repo.require_run('r') == before and not repo.list_calls('r')


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_new_plan_edit_contract_cannot_be_disabled_by_client_or_later_update(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=Mock())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '研究方法',
            'planEditContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['planEditContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'planEditContractVersion': replacement})
    finally:
        facade.shutdown()
