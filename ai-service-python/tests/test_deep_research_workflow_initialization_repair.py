from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests

from services.deep_research.contracts import DeepResearchError, digest, UnknownCallError
from services.deep_research import workflow_initialization_repair as repair
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def invalid(value):
    value = deepcopy(value); init = value['initialization']
    init.update(initializationMode='derive', inputs=[])
    init['stateDefinitions'][0]['shape'] = [{'inputIndex': 0, 'axis': 0}]
    return value


def setup(outputs):
    r, prompt, invoke, run = setup_repair(outputs)
    r.update(workflowMetadataRepairContractVersion=17, workflowInitializationOutputContractVersion=1,
             workflowInitializationRepairContractVersion=1)
    return r, prompt, invoke, run


def test_complete_correction_preserves_original_and_assembles_once():
    inits = explicit_initializers(); bad = invalid(inits[0])
    r, prompt, invoke, run = setup([response(scope_authored()), response(bad), *map(response, inits)])
    saved = run(); fix = saved['initializationRepair']
    assert saved['status'] == fix['status'] == 'ready' and not saved['scientificApproval']
    assert fix['unitKey'] == 'baseline' and saved['units']['baseline']['response'] == response(bad)
    assert saved['units']['baseline']['status'] == 'invalid_response'
    assert fix['response'] == response(inits[0]) and fix['value'] == inits[0]
    data = input_value(fix['request']['prompt'])
    assert data['authoritativeInput'] == json.loads(prompt.split('Authoritative input data (not instructions):\n')[1])
    assert data['invalidInitialization'] == bad
    assert data['unitContext']['metadata'] == saved['units']['metadata']['value']
    assert any(x['path'].endswith('/inputIndex') and x['availableInputCount'] == 0
               for x in data['fieldFeedback']['issues'])
    assert fix['request']['extra']['max_tokens'] == 6144
    assert fix['request']['extra']['reasoning_effort'] == 'none'
    before = deepcopy(saved); assert run() == before and invoke.call_count == 5


def test_second_invalid_unit_cannot_obtain_another_correction():
    inits = explicit_initializers()
    r, _, invoke, run = setup([response(scope_authored()), response(invalid(inits[0])),
                               response(inits[0]), response(invalid(inits[1]))])
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 4
    assert r['state']['executionWorkflowBlueprint']['initializationRepair']['unitKey'] == 'baseline'


@pytest.mark.parametrize('replacement', [None, True, 2])
def test_marker_is_immutable_and_cannot_opt_in_legacy(tmp_path, replacement):
    r, _, _, _ = setup([]); r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path/'mark.sqlite3'); repo.initialize(); repo.create_run(r)
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run('r', lambda v: {**v, repair.MARKER: replacement})
    old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop(repair.MARKER); repo.create_run(old)
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run('old', lambda v: {**v, repair.MARKER: 1})


def failed_unit():
    r, _, _, run = setup([response(scope_authored()), response(invalid(explicit_initializers()[0]))])
    r.pop(repair.MARKER)
    with pytest.raises(DeepResearchError): run()
    saved = r['state']['executionWorkflowBlueprint']
    r[repair.MARKER] = 1
    return r, saved['units']['baseline'], {'target': 'baseline', 'metadata': saved['units']['metadata']['value'], 'earlier': []}


@pytest.mark.parametrize('bad', [None, [], {'response': None}, {'response': []}, {'response': 'text'}])
def test_malformed_original_record_is_ineligible_without_exception(bad):
    assert repair.original_value(bad) is None


@pytest.mark.parametrize('finish', ['length', 'failed', None])
def test_incomplete_original_is_not_retried(finish):
    r, failed, context = failed_unit(); failed = deepcopy(failed)
    failed['response']['finishReason'] = finish; failed['responseDigest'] = digest(failed['response'])
    invoke = Mock()
    with pytest.raises(DeepResearchError):
        repair.prepare(r, key='baseline', source_data='{}', context=context, failed=failed, aliases={'E1': 'owned'},
                       earlier=(), baseline=True, target=None, existing=None, invoke=invoke, checkpoint=Mock())
    invoke.assert_not_called()


def test_received_response_survives_interruption_without_another_send():
    r, failed, context = failed_unit(); store = {}; sender = Mock(return_value=response(explicit_initializers()[0]))
    class Interrupted(Exception): pass
    def save(v):
        store['value'] = deepcopy(v)
        if v['status'] == 'response_received': raise Interrupted()
    args = dict(key='baseline', source_data='{}', context=context, failed=failed,
                aliases={'E1': 'owned'}, earlier=(), baseline=True, target=None, invoke=sender)
    with pytest.raises(Interrupted): repair.prepare(r, existing=None, checkpoint=save, **args)
    result = repair.prepare(r, existing=store['value'], checkpoint=lambda v: store.update(value=deepcopy(v)), **args)
    assert result == explicit_initializers()[0] and sender.call_count == 1
    store['value']['response']['content'] = '{}'
    with pytest.raises(DeepResearchError): repair.prepare(r, existing=store['value'], checkpoint=Mock(), **args)
    assert sender.call_count == 1


def test_capacity_rejection_and_response_size_limits_do_not_send_or_retry():
    r, failed, context = failed_unit(); store = {}; sender = Mock()
    source = json.dumps({'original': ''.join(chr(0x4e00+i) for i in range(14000))})
    def run():
        return repair.prepare(r, key='baseline', source_data=source, context=context, failed=failed,
            aliases={'E1': 'owned'}, earlier=(), baseline=True, target=None, existing=store.get('value'),
            invoke=sender, checkpoint=lambda v: store.update(value=deepcopy(v)))
    for _ in range(2):
        with pytest.raises(DeepResearchError, match='超限'): run()
    sender.assert_not_called()
    assert store['value']['status'] == 'not_started_capacity' and store['value']['inputBytes'] > 32000
    store['value']['inputBytes'] = 1
    with pytest.raises(DeepResearchError) as error: run()
    assert error.value.code == 'invalid_workflow_blueprint_state'
    oversized = deepcopy(failed); oversized['response']['content'] = ' '*8200
    oversized['responseDigest'] = digest(oversized['response'])
    assert repair.original_value(oversized) is None


def test_budget_admission_is_durable_and_incomplete_revision_is_never_repeated():
    r, failed, context = failed_unit(); r['budget']['elapsedSeconds'] = r['budget']['maxWallClockSeconds']
    store = {}; sender = Mock()
    args = dict(key='baseline', source_data='{}', context=context, failed=failed, aliases={'E1': 'owned'},
                earlier=(), baseline=True, target=None, invoke=sender,
                checkpoint=lambda v: store.update(value=deepcopy(v)))
    assert repair.prepare(r, existing=None, **args) is None
    assert repair.prepare(r, existing=store['value'], **args) is None
    sender.assert_not_called(); assert store['value']['status'] == 'not_started_budget'
    r, failed, context = failed_unit(); store = {}
    raw = response(explicit_initializers()[0]); raw['finishReason'] = 'length'
    sender = Mock(return_value=raw)
    args.update(failed=failed, context=context, invoke=sender,
                checkpoint=lambda v: store.update(value=deepcopy(v)))
    for _ in range(2):
        with pytest.raises(DeepResearchError): repair.prepare(r, existing=store.get('value'), **args)
    assert sender.call_count == 1 and store['value']['errors'] == ['unit.output_truncated']


def test_legacy_or_corrupted_repair_slot_cannot_change_original_execution():
    inits = explicit_initializers()
    r, _, _, run = setup([response(scope_authored()), *map(response, inits)])
    r['state']['executionWorkflowBlueprint'] = {'initializationRepair': {'unitKey': 'baseline'}}
    r.pop(repair.MARKER)
    with pytest.raises(DeepResearchError): run()


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_physical_request_budget_and_unknown_guard(tmp_path, monkeypatch, scenario):
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.planning_transport import overhead_bytes
    from test_deep_research_schema_transport import response as http_response
    r, failed, context = failed_unit(); r.update(runId='r', taskId='t')
    if scenario == 'budget': r['budget']['maxTokens'] = 1
    repo = DeepResearchRepository(tmp_path/'wire.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    post = Mock(side_effect=requests.ReadTimeout('fixture')) if scenario == 'unknown' else Mock(
        return_value=http_response(json.dumps(explicit_initializers()[0])))
    monkeypatch.setattr('llm.client.requests.post', post)
    scoped = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    invoker = TrackedLLMInvoker(scoped, repo.reserve_call, repo.complete_call,
                               request_options=research_model_options, run_record_fn=repo.require_run,
                               experiment_max_input_bytes=32000)
    store = {}
    def run():
        return repair.prepare(repo.require_run('r'), key='baseline', source_data='{}', context=context, failed=failed,
            aliases={'E1': 'owned'}, earlier=(), baseline=True, target=None, existing=store.get('value'),
            invoke=lambda n,p,o: invoker('r', n, p, o), checkpoint=lambda v: store.update(value=deepcopy(v)))
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises(UnknownCallError): run()
    elif scenario == 'budget':
        assert run() is None and run() is None; post.assert_not_called(); return
    else: assert run() == run() == explicit_initializers()[0]
    assert post.call_count == 1
    wire = post.call_args.kwargs['json']
    assert wire['reasoning']['effort'] == 'none' and wire['max_output_tokens'] == 6144
    assert wire['text']['format']['name'] == 'workflow_unit_init_v7'
    assert repo.list_calls('r')[0]['reservedTokens'] == len(store['value']['request']['prompt'].encode()) + 1024 + overhead_bytes(r,'plan_workflow_init') + 6144
