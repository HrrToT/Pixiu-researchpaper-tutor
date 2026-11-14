import asyncio
import json
import threading
from unittest.mock import Mock

import pytest
import requests

from services.deep_research.facade import ResearchFacade
from services.deep_research.runtime import AuthoritativeScopeValidator


def source_inputs():
    sources = [dict(sourceId=f's{i}', workId=f'p{i % 2}', contentHash=f'h{i}',
                    text='Private full passage') for i in range(40)]
    sources += [dict(sourceId='foreign', workId='foreign', contentHash='foreign', text='Secret')]
    evidence = [dict(evidenceId=f'e{i}', sourceId=f's{i}', sourceWorkId=f'p{i % 2}',
                     contentHash=f'h{i}', quote=f'Exact quote {i}', location={'page': i + 1})
                for i in range(40)]
    record = dict(taskId='task', materials=[{'materialId': 'p0'}, {'materialId': 'p1'}],
                  materialSnapshot={'snapshotHash': 'snapshot'}, state={'sources': sources, 'evidence': evidence})
    repo = Mock()
    repo.require_run.return_value = record
    post = Mock(return_value=Mock(status_code=200, content=b'{}'))
    post.return_value.json.return_value = dict(valid=True, snapshotValid=True, taskId='task', runId='run')
    return repo, post


def test_many_passages_require_one_live_snapshot_check_per_read_and_preserve_exact_quotes():
    repo, post = source_inputs()
    model = Mock()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=model,
                            scope_validator=AuthoritativeScopeValidator(repo, post=post))
    try:
        projected = facade.get_sources('run')
        assert len(projected) == 40 and post.call_count == 1
        for i, item in enumerate(projected):
            assert item['quote'] == f'Exact quote {i}'
            assert item['evidenceQuotes'] == {f'e{i}': {'quote': f'Exact quote {i}', 'location': {'page': i + 1}}}
            assert 'text' not in item
        post.return_value.json.return_value['snapshotValid'] = False
        assert facade.get_sources('run') == [] and post.call_count == 2
        model.invoke.assert_not_called()
        repo.update_run.assert_not_called()
    finally:
        facade.shutdown(wait=True)


@pytest.mark.parametrize('failure', ['redirect', 'timeout', 'foreign_run'])
def test_batch_read_still_fails_closed(failure):
    repo, post = source_inputs()
    if failure == 'redirect':
        post.return_value.status_code = 302
    elif failure == 'timeout':
        post.side_effect = requests.Timeout('fixture unavailable')
    else:
        post.return_value.json.return_value['runId'] = 'foreign'
    validate = AuthoritativeScopeValidator(repo, post=post)
    assert validate.filter_materials('run', ['p0', 'p1', 'foreign']) == set()
    assert post.call_count == 1


def test_external_owners_require_live_scope_and_explicit_external_policy():
    repo, post = source_inputs()
    record = repo.require_run.return_value
    record['state']['sources'].append(dict(workId='arxiv:1234', sourceKind='arxiv'))
    validate = AuthoritativeScopeValidator(repo, post=post)
    assert validate.filter_materials('run', ['arxiv:1234', 'foreign']) == set()
    post.assert_not_called()
    record['sourcePolicy'] = {'mode': 'academic_external'}
    assert validate.filter_materials('run', ['p0', 'arxiv:1234', 'foreign']) == {'p0', 'arxiv:1234'}
    assert post.call_count == 1
    post.return_value.json.return_value['valid'] = False
    assert validate.filter_materials('run', ['arxiv:1234']) == set()
    assert post.call_count == 2


def test_injected_owner_policy_runs_once_per_owner_without_cross_read_cache():
    repo, _ = source_inputs()
    validate = Mock(side_effect=lambda _, owner: owner == 'p1')
    facade = ResearchFacade(repo, lambda **_: None, scope_validator=validate)
    try:
        assert len(facade.get_sources('run')) == 20
        assert validate.call_count == 3
        assert len(facade.get_sources('run')) == 20
        assert validate.call_count == 6
    finally:
        facade.shutdown(wait=True)


@pytest.mark.parametrize('route_name,args,method', [
    ('get_research_task', ('run',), 'get'),
    ('get_research_sources', ('run',), 'detail'),
    ('get_research_events', ('run',), 'detail'),
    ('get_research_action_receipt', ('run', 'req'), 'get_action_receipt'),
])
def test_blocked_read_does_not_block_other_requests(monkeypatch, route_name, args, method):
    from routes import research_routes
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    worker_threads = []
    dispatcher = Mock()

    def blocked(*_):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3), 'Test must release the blocking fixture'
        return {'status': 'success'}

    getattr(dispatcher, method).side_effect = blocked
    monkeypatch.setattr(research_routes, 'get_dispatcher', lambda: dispatcher)

    async def exercise():
        pending = asyncio.create_task(getattr(research_routes, route_name)(*args))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            # Another event-loop task must progress while the synchronous read
            # waits. No wall-clock performance threshold or real socket needed.
            progressed = []
            await asyncio.create_task(async_marker(progressed))
            assert progressed == ['responsive'] and not pending.done()
        finally:
            release.set()
        response = await pending
        assert response.status_code == 200
        assert json.loads(response.body) == {'status': 'success'}

    async def async_marker(items):
        items.append('responsive')

    asyncio.run(exercise())
    assert worker_threads and worker_threads[0] != main_thread
    getattr(dispatcher, method).assert_called_once()
    dispatcher.create.assert_not_called()
    dispatcher.action.assert_not_called()
