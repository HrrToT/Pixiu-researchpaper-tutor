from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError, digest, BudgetExhaustedError
from services.deep_research.workflow_metadata_rows import encode, decode, descriptor
from services.deep_research.workflow_metadata_repair import NODE, enabled, prepare, original_wire, prompt_for
from services.deep_research.workflow_units import META, unit_errors
from test_deep_research_workflow_lifecycle_units import fixtures, setup


def response(value, finish='stop'):
    return {'content': json.dumps(value), 'finishReason': finish}


def invalid_metadata():
    meta = fixtures()[1]
    meta['components'][0]['lifecycle']['createAfter'] = 'not_an_array'
    return meta


def failed_unit():
    meta = invalid_metadata(); raw = response(encode(meta))
    return {'request': {'prompt': 'original', 'extra': {}}, 'response': raw,
            'responseDigest': digest(raw), 'value': meta, 'valueDigest': digest(meta),
            'status': 'invalid_response', 'errors': unit_errors(meta, {'E1': 'owned'}, node=META,
                                                              version=7, metadata_rows=True)}


def failed_wire_unit():
    wire = encode(fixtures()[1]); wire['phaseRows'][0][6] = ['baseline']
    raw = response(wire)
    return {'request': {'prompt': 'original', 'extra': {}}, 'response': raw,
            'responseDigest': digest(raw), 'value': None, 'valueDigest': digest(None),
            'status': 'invalid_response', 'errors': ['unit.json']}


def setup_repair(outputs=None):
    r, prompt, invoke, run = setup()
    r.update(workflowMetadataRowsContractVersion=2, workflowMetadataRepairContractVersion=1)
    _, meta, inits = fixtures()
    invoke.side_effect = outputs if outputs is not None else [
        response(encode(invalid_metadata())), response(encode(meta)), *[response(v) for v in inits]]
    return r, prompt, invoke, run


def test_one_separate_revision_preserves_failed_unit_and_complete_assembly_and_resumes():
    r, _, invoke, run = setup_repair()
    saved = run(); expected, _, _ = fixtures()
    expected['records'] = saved['value']['workflow']['records']
    assert saved['value']['workflow'] == expected and saved['status'] == 'ready'
    assert saved['units']['metadata']['status'] == 'invalid_response'
    assert saved['metadataRepair']['status'] == 'ready' and not saved['metadataRepair']['scientificApproval']
    assert saved['request']['metadataRepairContract'] == 1
    assert [v.args[0] for v in invoke.call_args_list].count(NODE) == 1 and invoke.call_count == 5
    assert run() == saved and invoke.call_count == 5 and not saved['scientificApproval']
    assert saved['metadataRepair']['parent']['valueDigest'] == saved['units']['metadata']['valueDigest']


def test_version2_repairs_complete_bad_leaf_wire_without_constructing_an_original_value():
    _, meta, inits = fixtures(); bad = failed_wire_unit()['response']
    r, _, invoke, run = setup_repair([bad, response(encode(meta)), *[response(v) for v in inits]])
    r['workflowMetadataRepairContractVersion'] = 2
    saved = run()
    assert saved['units']['metadata']['value'] is None
    assert saved['units']['metadata']['errors'] == ['unit.json']
    assert saved['metadataRepair']['version'] == 2 and saved['metadataRepair']['status'] == 'ready'
    assert saved['request']['metadataRepairContract'] == 2
    assert run() == saved and invoke.call_count == 5 and not saved['scientificApproval']
    r['workflowMetadataRepairContractVersion'] = 1
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_blueprint_state' and invoke.call_count == 5


@pytest.mark.parametrize('change', ['truncated', 'json_prefix', 'row_arity', 'extra_root'])
def test_version2_still_refuses_truncated_or_ambiguous_originals(change):
    unit = failed_wire_unit()
    if change == 'truncated': unit['response']['finishReason'] = 'length'
    elif change == 'json_prefix': unit['response']['content'] = '{'
    else:
        wire = json.loads(unit['response']['content'])
        if change == 'row_arity': wire['phaseRows'][0].pop()
        else: wire['unrecognized'] = 'not dropped'
        unit['response']['content'] = json.dumps(wire)
    unit['responseDigest'] = digest(unit['response'])
    assert original_wire(unit, version=2) is None


def test_version1_complete_wire_gate_stays_frozen_for_bad_leaf_values():
    unit = failed_wire_unit()
    assert original_wire(unit, version=1) is None
    assert original_wire(unit, version=2) == json.loads(unit['response']['content'])


@pytest.mark.parametrize('where', ['root', 'nested'])
def test_version2_rejects_duplicate_keys_without_silently_selecting_one(where):
    unit = failed_wire_unit(); raw = unit['response']['content']
    if where == 'root': changed = '{"baselineMode":"existing",' + raw[1:]
    else: changed = raw.replace('"checkpointSelection": {"mode": "fixed_budget"}',
                                '"checkpointSelection": {"mode":"existing","mode":"fixed_budget"}')
    assert changed != raw
    unit['response']['content'] = changed; unit['responseDigest'] = digest(unit['response'])
    assert original_wire(unit, version=2) is None


def test_version2_revision_response_with_duplicate_keys_stays_invalid_and_is_not_resent():
    good = json.dumps(encode(fixtures()[1]))
    revised = {'content': '{"baselineMode":"existing",' + good[1:], 'finishReason': 'stop'}
    r, _, invoke, run = setup_repair([failed_wire_unit()['response'], revised])
    r['workflowMetadataRepairContractVersion'] = 2
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    assert r['state']['executionWorkflowBlueprint']['metadataRepair']['errors'] == ['unit.json']


def test_version2_does_not_accept_an_ambiguous_original_just_because_its_last_value_validates():
    good = json.dumps(encode(fixtures()[1]))
    ambiguous = {'content': '{"baselineMode":"existing",' + good[1:], 'finishReason': 'stop'}
    r, _, invoke, run = setup_repair([ambiguous]); r['workflowMetadataRepairContractVersion'] = 2
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_unit_response' and invoke.call_count == 1
    assert 'metadataRepair' not in r['state']['executionWorkflowBlueprint']


@pytest.mark.parametrize('change', ['length', 'malformed', 'failed_status', 'capacity'])
def test_ineligible_original_has_no_revision_or_second_send(change):
    bad = response(encode(invalid_metadata()))
    if change == 'length': bad['finishReason'] = 'length'
    elif change == 'malformed': bad['content'] = '{'
    elif change == 'failed_status': bad['finishReason'] = 'responses_failed'
    else: bad['content'] = json.dumps(encode(invalid_metadata())) + ' ' * 8200
    r, _, invoke, run = setup_repair([bad])
    for _ in range(2):
        with pytest.raises(DeepResearchError) as exc: run()
        assert exc.value.code == 'invalid_workflow_unit_response'
    assert invoke.call_count == 1 and 'metadataRepair' not in r['state']['executionWorkflowBlueprint']


@pytest.mark.parametrize('change', ['invalid', 'truncated', 'failed_status', 'malformed'])
def test_invalid_revision_is_cached_without_a_second_revision(change):
    revised = response(encode(fixtures()[1]))
    if change == 'invalid': revised = response(encode(invalid_metadata()))
    elif change == 'truncated': revised['finishReason'] = 'length'
    elif change == 'failed_status': revised['finishReason'] = 'responses_failed'
    else: revised['content'] = '{'
    r, _, invoke, run = setup_repair([response(encode(invalid_metadata())), revised])
    for _ in range(2):
        with pytest.raises(DeepResearchError) as exc: run()
        assert exc.value.code == 'invalid_workflow_unit_response'
    assert invoke.call_count == 2
    assert r['state']['executionWorkflowBlueprint']['metadataRepair']['status'] == 'invalid_response'


@pytest.mark.parametrize('change', ['request', 'raw', 'value', 'parent', 'approval', 'missing', 'contract'])
def test_changed_revision_cannot_be_reinterpreted_or_resent(change):
    r, _, invoke, run = setup_repair(); run()
    state = r['state']['executionWorkflowBlueprint']; child = state['metadataRepair']
    if change == 'request': child['request']['prompt'] += 'changed'
    elif change == 'raw': child['response']['content'] += ' '
    elif change == 'value': child['value']['frameIterations'] += 1
    elif change == 'parent': child['parent']['valueDigest'] = 'changed'
    elif change == 'approval': child['scientificApproval'] = True
    elif change == 'missing': del state['metadataRepair']
    else: del r['workflowMetadataRepairContractVersion']
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_blueprint_state' and invoke.call_count == 5


def test_valid_original_never_uses_revision_and_legacy_invalid_metadata_keeps_old_behavior():
    _, meta, inits = fixtures()
    r, _, invoke, run = setup_repair([response(encode(meta)), *[response(v) for v in inits]])
    run(); assert invoke.call_count == 4 and 'metadataRepair' not in r['state']['executionWorkflowBlueprint']
    r, _, invoke, run = setup_repair([response(encode(invalid_metadata()))])
    del r['workflowMetadataRepairContractVersion']
    with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 1


def test_revision_input_capacity_is_saved_before_any_send_and_cannot_be_cleared():
    r, _, _, _ = setup_repair(); states = []; invoke = Mock()
    def checkpoint(v): states[:] = [deepcopy(v)]
    args = dict(source_data=json.dumps({'evidence': 'x' * 40000}), failed=failed_unit(),
                aliases={'E1': 'owned'}, invoke=invoke, checkpoint=checkpoint)
    with pytest.raises(DeepResearchError) as exc: prepare(r, existing=None, **args)
    assert exc.value.code == 'workflow_blueprint_input_capacity'
    assert states[0]['status'] == 'not_started_capacity' and states[0]['inputBytes'] > 32000
    changed = deepcopy(states[0]); changed['status'] = 'pending'
    with pytest.raises(DeepResearchError) as exc: prepare(r, existing=changed, **args)
    assert exc.value.code == 'invalid_workflow_blueprint_state'; invoke.assert_not_called()


def test_time_and_atomic_budget_refusal_are_durable_without_second_invocation():
    r, _, _, _ = setup_repair(); states = []
    invoke = Mock(side_effect=BudgetExhaustedError('tokens', 100000, 100001))
    def checkpoint(v): states[:] = [deepcopy(v)]
    args = dict(source_data='{}', failed=failed_unit(), aliases={'E1': 'owned'},
                invoke=invoke, checkpoint=checkpoint)
    assert prepare(r, existing=None, **args) is None
    assert states[0]['status'] == 'not_started_budget'
    assert prepare(r, existing=states[0], **args) is None and invoke.call_count == 1
    r['budget']['elapsedSeconds'] = 359
    invoke.reset_mock(); states.clear()
    assert prepare(r, existing=None, **args) is None
    invoke.assert_not_called()


def test_shared_repair_input_restores_all_source_values_failed_wire_and_feedback():
    from services.deep_research.shared_strings import unpack as strings
    from services.deep_research.nested_tables import unpack as tables
    from services.deep_research.workflow_metadata_feedback import feedback
    source = {'evidence': [{'id': str(i), 'quote': '原文 '+str(i), 'sourceId': 'same-source'*10}
                           for i in range(40)], 'literal': {'$': 0}, 'question': 'complete original objective'}
    failed = failed_unit(); wire = original_wire(failed); f = feedback(failed['value'], {'E1': 'owned'})
    text = prompt_for(json.dumps(source, ensure_ascii=False), wire, f)
    data = json.loads(text.split('\n', 1)[1].split('\n', 1)[0])
    restored = tables(strings(data))
    assert digest(restored) == digest({'authoritativeInput': source, 'invalidMetadata': wire, 'fieldFeedback': f})


def test_valid_revision_cannot_bypass_later_initialization_or_publish_an_incomplete_workflow():
    _, meta, inits = fixtures(); inits[0]['initialization']['stateDefinitions'] = []
    r, _, invoke, run = setup_repair([response(encode(invalid_metadata())), response(encode(meta)),
                                     *[response(v) for v in inits]])
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_unit_response' and invoke.call_count == 3
    state = r['state']['executionWorkflowBlueprint']
    assert state['metadataRepair']['status'] == 'ready' and state['status'] == 'pending'
    assert 'value' not in state and not state['scientificApproval']


def test_received_revision_is_saved_before_checks_and_replayed_without_another_send():
    r, _, _, _ = setup_repair(); failed = failed_unit(); received = []
    invoke = Mock(return_value=response(encode(fixtures()[1])))
    class SimulatedInterruption(Exception): pass
    def interrupted(v):
        received[:] = [deepcopy(v)]
        if v['status'] == 'response_received': raise SimulatedInterruption()
    args = dict(source_data='{}', failed=failed, aliases={'E1': 'owned'}, invoke=invoke)
    with pytest.raises(SimulatedInterruption): prepare(r, existing=None, checkpoint=interrupted, **args)
    assert received[0]['status'] == 'response_received' and invoke.call_count == 1
    result = prepare(r, existing=received[0], checkpoint=lambda v: received.__setitem__(slice(None), [v]), **args)
    assert result == fixtures()[1] and invoke.call_count == 1


def test_client_cannot_override_the_server_revision_contract(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path/'api.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        row, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'fixture', 'question': 'Design',
            'workflowMetadataRepairContractVersion': 999, 'deferStart': True}, start_async=False)
        assert row['workflowMetadataRepairContractVersion'] == 19 and enabled(row)
    finally: facade.shutdown()


@pytest.mark.parametrize('invalid_initializer', [False, True])
def test_graph_uses_revision_once_and_requires_complete_initial_state_before_public_body(invalid_initializer):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_planning import Store
    from test_deep_research_scientific_outline import record, value as outline
    from test_deep_research_workflow5_contract import claims
    store = Store(record()); store.value.update(workflowMetadataRowsContractVersion=2,
                                               workflowMetadataRepairContractVersion=1)
    _, meta, inits = fixtures(); bad = invalid_metadata()
    for v in [meta, bad, *inits]: v['sourceRefs'] = []
    if invalid_initializer: inits[0]['initialization']['stateDefinitions'] = []
    rows = claims(); rows[-1].pop('executionSpec')
    invoke = Mock(side_effect=[response(v) for v in [outline(), encode(bad), encode(meta),
                                                     *inits, {'sections': [], 'claims': rows}]])
    if invalid_initializer:
        with pytest.raises(DeepResearchError): make_synthesize_node(invoke, store.update)({'run_id': 'r'})
        assert 'reportBody' not in store.value['state']
    else:
        result = make_synthesize_node(invoke, store.update)({'run_id': 'r'})
        assert not result.get('error_code'), result
        assert store.value['state']['executionWorkflowBinding']['scientificApproval'] is False
        step = next(c for c in store.value['state']['reportBody']['claims'] if c['designRole'] == 'steps')
        assert step['executionSpec']['componentInitializations'][0]['stateDefinitions']
    assert store.value['state']['executionWorkflowBlueprint']['metadataRepair']['status'] == 'ready'
    assert [call.args[1] for call in invoke.call_args_list].count(NODE) == 1


def test_revision_and_original_error_journal_resume_across_python_hash_seeds_without_calls(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = '''import sys,json
from pathlib import Path
from copy import deepcopy
sys.path[:0]=['ai-service-python','ai-service-python/tests']
from test_deep_research_workflow_metadata_repair import setup_repair,response
from test_deep_research_workflow_lifecycle_units import fixtures
from services.deep_research.workflow_metadata_rows import encode
from services.deep_research.contracts import digest
_,meta,inits=fixtures();bad=deepcopy(meta);a,b=bad['components'][0]['appliesTo'][:2]
for p in bad['phases']:
 if p['kind']=='evaluate':p['groups']=[a]
p=deepcopy(next(p for p in bad['phases'] if p['kind']=='fit'))
p.update(phaseId='late_fit_probe',groups=[a],after=[],reads=[],updates=[],outputs=[])
bad['phases'].insert(-1,p)
r,_,invoke,run=setup_repair([response(encode(bad)),response(encode(meta)),*[response(v) for v in inits]])
path=Path(sys.argv[1])
if path.exists():
 r.update(json.loads(path.read_text(encoding='utf8')))
 invoke.side_effect=AssertionError('Resume must not send any new request')
result=run()
if not path.exists():path.write_text(json.dumps(r),encoding='utf8')
print(json.dumps({'requestDigest':digest(result['metadataRepair']['request']),'calls':invoke.call_count}))
'''
    root = Path(__file__).resolve().parents[2]; path = tmp_path/'record.json'; results = []
    for seed in ('1', '2'):
        run = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(path)], cwd=root,
            env={**os.environ, 'PYTHONHASHSEED': seed}, capture_output=True, text=True, encoding='utf8', check=True)
        results.append(json.loads(run.stdout))
    assert results[0]['requestDigest'] == results[1]['requestDigest']
    assert results[0]['calls'] == 5 and results[1]['calls'] == 0


@pytest.mark.parametrize('replacement', [None, True, 2])
def test_marker_is_immutable_and_legacy_records_cannot_be_opted_in(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    r, _, _, _ = setup_repair(); r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path/'marker.sqlite3'); repo.initialize(); repo.create_run(r)
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run('r', lambda row: {**row, 'workflowMetadataRepairContractVersion': replacement})
    old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); del old['workflowMetadataRepairContractVersion']
    repo.create_run(old)
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run('old', lambda row: {**row, 'workflowMetadataRepairContractVersion': 1})


@pytest.mark.parametrize('revision_version', [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget', 'token_budget'])
def test_physical_request_identity_unknown_deduplication_and_existing_whole_budget(tmp_path, monkeypatch, scenario, revision_version):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from services.deep_research.contracts import UnknownCallError, UnresolvedUnknownError
    from test_deep_research_scientific_outline import record
    from test_deep_research_schema_transport import response as http_response
    r = record(); r.update(runId='r', taskId='t', workflowMetadataRowsContractVersion=2,
                           workflowMetadataRepairContractVersion=revision_version)
    if scenario == 'budget': r['budget'].update(modelCalls=13, reservedModelCalls=5)
    if scenario == 'token_budget': r['budget']['maxTokens'] = 1
    repo = DeepResearchRepository(tmp_path/'wire.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    from services.deep_research.workflow_metadata_actions import encode as action_encode, descriptor as action_descriptor
    reply_encode = action_encode if revision_version in (6, 7) else encode
    reply_descriptor = action_descriptor if revision_version in (6, 7) else descriptor
    if revision_version in (8, 9, 10):
        from services.deep_research.workflow_metadata_objects import encode as reply_encode, descriptor as reply_descriptor
    failed = failed_unit() if revision_version == 1 else failed_wire_unit()
    if revision_version in (8, 9, 10):
        meta = invalid_metadata(); raw = response(meta)
        failed.update(response=raw,responseDigest=digest(raw),value=meta,valueDigest=digest(meta),
            errors=unit_errors(meta, {'E1':'owned'}, node=META, version=7, metadata_rows=True))
    if revision_version in (11, 12):
        from test_deep_research_workflow_metadata_ordered_integration import failed_ordered_unit
        from test_deep_research_workflow_metadata_ordered import authored
        from services.deep_research.workflow_metadata_ordered import descriptor as ordered_descriptor
        reply_descriptor = lambda: ordered_descriptor(version=2 if revision_version == 12 else 1)
        reply_encode = lambda _: authored()
        failed = failed_ordered_unit()
    if revision_version == 13:
        from test_deep_research_workflow_metadata_steps_integration import failed_step_unit
        from test_deep_research_workflow_metadata_steps import observations
        from services.deep_research.workflow_metadata_steps import descriptor as reply_descriptor
        reply_encode = lambda _: observations()
        failed = failed_step_unit()
    if revision_version == 14:
        from test_deep_research_workflow_metadata_single_group_integration import failed_scalar_unit
        from test_deep_research_workflow_metadata_single_group import authored as scalar_authored
        from services.deep_research.workflow_metadata_single_group import descriptor as reply_descriptor
        reply_encode = lambda _: scalar_authored()
        failed = failed_scalar_unit()
    if revision_version == 15:
        from test_deep_research_workflow_metadata_single_group_integration import failed_scalar_unit
        from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
        from services.deep_research.workflow_metadata_scope_end import descriptor as reply_descriptor
        reply_encode = lambda _: scope_authored()
        failed = failed_scalar_unit()
    if revision_version == 16:
        from functools import partial
        from test_deep_research_workflow_metadata_single_group_integration import failed_scalar_unit
        from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
        from services.deep_research.workflow_metadata_scope_end import descriptor as count_descriptor
        reply_descriptor = partial(count_descriptor, frame_count_rules=True)
        reply_encode = lambda _: scope_authored()
        failed = failed_scalar_unit()
    if revision_version == 17:
        from functools import partial
        from test_deep_research_workflow_metadata_single_group_integration import failed_scalar_unit
        from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
        from services.deep_research.workflow_metadata_scope_end import descriptor as compact_descriptor
        reply_descriptor = partial(compact_descriptor, frame_count_rules=True, compact_rules=True)
        reply_encode = lambda _: scope_authored()
        failed = failed_scalar_unit()
    post = Mock(side_effect=requests.ReadTimeout('fixture unknown')) if scenario == 'unknown' else Mock(
        return_value=http_response(json.dumps(reply_encode(fixtures()[1]))))
    monkeypatch.setattr('llm.client.requests.post', post)
    scoped = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    invoke = TrackedLLMInvoker(scoped, repo.reserve_call, repo.complete_call,
        request_options=research_model_options, run_record_fn=repo.require_run, experiment_max_input_bytes=32000)
    def checkpoint(v): repo.update_run('r', lambda row: {**row, 'state': {**row['state'], 'repairFixture': v}})
    def run():
        row = repo.require_run('r')
        return prepare(row, source_data='{}', failed=failed, aliases={'E1': 'owned'},
            existing=row['state'].get('repairFixture'),
            invoke=lambda n, p, o: invoke('r', n, p, o, use_reserve=True), checkpoint=checkpoint)
    if scenario in ('budget', 'token_budget'):
        assert run() is None and run() is None
        post.assert_not_called(); return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises((UnknownCallError, UnresolvedUnknownError)): run()
    else:
        result = run(); assert run() == result and not result.get('scientificApproval', False)
    assert post.call_count == 1
    saved = repo.require_run('r')['state']['repairFixture']; call = repo.list_calls('r')[0]
    assert digest(saved['request']) == call['argsDigest']
    from services.deep_research.planning_transport import overhead_bytes
    expected_reserved = (len(saved['request']['prompt'].encode('utf8')) + 1024
        + overhead_bytes(r, NODE) + (6144 if revision_version == 10 else 3072 if revision_version in (4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17) else 2048))
    assert call['reservedTokens'] == expected_reserved
    wire = post.call_args.kwargs['json']
    assert wire['text']['format'] == reply_descriptor() and wire['max_output_tokens'] == (6144 if revision_version == 10 else 3072 if revision_version in (4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17) else 2048)
    assert wire['reasoning']['effort'] == ('low' if revision_version == 10 else 'none')
