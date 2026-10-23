import json

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research import runtime
from services.deep_research.publication import PublicationDispatcher
from test_deep_research_claim_isolation import facts


@pytest.fixture
def production_factory(tmp_path, monkeypatch):
    captured = []
    class Provider:
        def invoke(self, request):
            targets = json.JSONDecoder().raw_decode(request.prompt.split('Claims:\n', 1)[1])[0]
            captured.append((targets, request.prompt))
            return LLMResult('fixture', 'fixture', json.dumps({'items': [
                {'claimId': c['claimId'], 'status': 'passed'} for c in targets]}), LLMUsage(1, 1, 2), 'stop')
    monkeypatch.setattr(runtime, '_runtime', None)
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED', 'true')
    monkeypatch.setenv('DEEP_RESEARCH_DB_PATH', str(tmp_path / 'runtime.sqlite3'))
    monkeypatch.setattr(runtime, 'research_model', lambda: Provider())
    monkeypatch.setattr(runtime.AuthoritativeScopeValidator, 'validate_materials', lambda *_: True)
    monkeypatch.setattr(PublicationDispatcher, 'start', lambda self: None)
    monkeypatch.setattr(runtime, 'configure_dispatcher', lambda _: None)
    facade = runtime.initialize_runtime()
    try:
        yield facade, captured
    finally:
        facade.shutdown(wait=True)
        runtime._runtime = None


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('revision', [False, True])
def test_real_runtime_factory_respects_new_isolation_and_preserves_historical_batches(production_factory, legacy, revision):
    facade, captured = production_factory
    if legacy:
        facade._repo.create_run({'runId': 'old', 'taskId': 'task', 'question': '核查主张',
            'claimIsolationContractVersion': 1, 'structuredOutputContractVersion': 4})
        rid = 'old'
    else:
        record, _ = facade.create({'workspaceTaskId': 'task', 'operationKey': 'op',
            'question': '核查主张', 'deferStart': True}, start_async=False)
        rid = record['runId']
        assert record['runtimeSemanticContractVersion'] == 1
    facade._repo.begin_execution(rid)
    checker = facade._make_semantic_checker(rid)
    claims, evidence = facts()
    result = checker.check_revisions(claims, evidence, []) if revision else checker(claims, evidence)
    assert [v['claimId'] for v in result] == ['a', 'b', 'c']
    assert len(captured) == (1 if legacy else 3)
    if not legacy:
        for targets, prompt in captured:
            assert len(targets) == 1
            key = targets[0]['claimId']
            assert 'OWN ORIGINAL '+key in prompt
            assert all('OWN ORIGINAL '+other not in prompt for other in ('a', 'b', 'c') if other != key)
    calls = facade._repo.list_calls(rid)
    assert len(calls) == len(captured) and all(c['status'] == 'succeeded' for c in calls)
    assert {c['node'] for c in calls} == {'verify_repair' if revision else 'verify'}


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_actual_runtime_policy_is_server_owned_and_frozen(production_factory, replacement):
    facade, _ = production_factory
    record, _ = facade.create({'workspaceTaskId': 'task', 'operationKey': 'op',
        'question': '核查主张', 'deferStart': True, 'runtimeSemanticContractVersion': replacement}, start_async=False)
    assert record['runtimeSemanticContractVersion'] == 1
    with pytest.raises(ValueError, match='Immutable'):
        facade._repo.update_run(record['runId'], lambda r: {**r, 'runtimeSemanticContractVersion': replacement})
