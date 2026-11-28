"""Opt-in durable declarations bind both first initialization and sole repair."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_representation_stage as stage
from services.deep_research.contracts import DeepResearchError, BudgetExhaustedError, digest
from services.deep_research.planning_transport import options_for_record, overhead_bytes, dispatch_options
from services.deep_research.workflow_units import INIT
from services.deep_research.workflow_initialization_wire import TARGET_OPTION
import test_deep_research_initialization_semantics as previous


def declaration(metadata, wires):
    names = ['baseline', *[c['componentId'] for c in metadata['components']]]
    targets, refs = [], set()
    for name, wire in zip(names, wires):
        init = wire['initialization']
        inputs = [init['input'], *init['additionalInputs']] if init['initializationMode'] == 'derive' else []
        meanings = {r[0]: r[1:] for r in wire['stateSemantics']}
        states = []
        refs.update(wire['sourceRefs'])
        for state in init['stateDefinitions']:
            shape = []
            for dim in state['shape']:
                if type(dim) is int: shape.append(dim)
                else:
                    source = inputs[dim['inputIndex']]
                    selected = source['selector']
                    shape.append({**{k:source[k] for k in ('state', 'phaseId', 'outputId') if k in source},
                        'entity':selected['entity'], 'fields':selected['fields'], 'axis':selected['axes'][dim['axis']]})
            states.append({'name':state['name'], 'dtype':state['dtype'], 'shape':shape,
                'quantity':meanings[state['name']][0], 'encoding':meanings[state['name']][1],
                'origin':'proposal', 'sourceRefs':wire['sourceRefs'], 'conventionRefs':[]})
        targets.append({'target':name, 'states':states})
    return {'sourceRefs':sorted(refs), 'targets':targets, 'conventions':[], 'unresolved':[]}


def setup():
    record, invoke, run = previous.setup()
    record[stage.MARKER] = 1
    calls = list(invoke.side_effect)
    metadata = json.loads(calls[0]['content'])
    value = declaration(metadata, [json.loads(c['content']) for c in calls[1:]])
    invoke.side_effect = [calls[0], {'content':json.dumps(value), 'finishReason':'stop'}, *calls[1:]]
    return record, invoke, run


def test_complete_workflow_reopens_without_new_declarations_and_keeps_full_inputs():
    record, invoke, run = setup()
    saved = run()
    assert saved['status'] == 'ready' and saved['representation']['status'] == 'ready'
    assert saved['representation']['scientificApproval'] is False
    assert saved['request']['representationContract'] == 1
    calls = invoke.call_args_list
    assert [c.args[0] for c in calls] == ['plan_workflow_meta', stage.NODE, INIT, INIT, INIT]
    assert 'Full 2x2 request, not shortened' in calls[1].args[1]
    for call in calls[2:]:
        assert 'Follow this frozen numeric interface' in call.args[1]
        assert call.args[2]['response_format']['name'].startswith('workflow_init_representation_v1_')
    assert run() == saved and invoke.call_count == 5
    from services.deep_research.execution_workflow_blueprint import instruction
    assert 'sharedRepresentation' in instruction(saved)


@pytest.mark.parametrize('marker', [None, False, True, 0, 2, '1'])
def test_version_and_parent_contracts_are_strict(marker):
    r = {**previous.record(), stage.MARKER:marker}
    assert stage.enabled(r) is (type(marker) is int and marker == 2)


def test_old_workflow_cannot_opt_in_and_resend():
    record, invoke, run = previous.setup()
    run(); count = invoke.call_count
    record[stage.MARKER] = 1
    with pytest.raises(DeepResearchError, match='原始输入不一致'):run()
    assert invoke.call_count == count


@pytest.mark.parametrize('change', ['declaration', 'metadata', 'raw_response', 'frozen', 'status', 'missing'])
def test_durable_shared_declaration_tampering_fails_before_any_new_call(change):
    record, invoke, run = setup()
    run(); count = invoke.call_count
    shared = record['state']['executionWorkflowBlueprint']['representation']
    if change == 'declaration': shared['value']['targets'][0]['states'][0]['dtype'] = 'float64'
    elif change == 'metadata': shared['metadata']['baselineMode'] = 'existing'
    elif change == 'raw_response': shared['response']['content'] = '{}'
    elif change == 'frozen': shared['frozen']['valueDigest'] = 'changed'
    elif change == 'status': shared['status'] = 'pending'
    else: record['state']['executionWorkflowBlueprint'].pop('representation')
    with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == count


def test_one_initializer_correction_must_obey_the_same_frozen_types():
    record, invoke, run = setup()
    calls = list(invoke.side_effect)
    good = deepcopy(calls[-1]); bad = deepcopy(good)
    wire = json.loads(bad['content']); wire['initialization']['stateDefinitions'][0]['dtype'] = 'other'
    bad['content'] = json.dumps(wire)
    invoke.side_effect = [*calls[:-1], bad, good]
    saved = run()
    assert saved['status'] == 'ready'
    repair = saved['initializationRepair']
    assert repair['status'] == 'ready' and 'representation.dtype_changed' in repair['parent']['errors']
    assert stage.OPTION in repair['request']['extra']
    assert 'Follow this frozen numeric interface' in repair['request']['prompt']
    count = invoke.call_count
    assert run() == saved and invoke.call_count == count


def test_invalid_correction_does_not_gain_a_second_try_or_update_shared_types():
    record, invoke, run = setup()
    calls = list(invoke.side_effect); bad = deepcopy(calls[-1])
    wire = json.loads(bad['content']); wire['initialization']['stateDefinitions'][0]['shape'][-1] = 123
    bad['content'] = json.dumps(wire)
    invoke.side_effect = [*calls[:-1], bad, bad]
    with pytest.raises(DeepResearchError): run()
    saved = record['state']['executionWorkflowBlueprint']
    assert saved['initializationRepair']['status'] == 'invalid_response'
    assert saved['representation']['status'] == 'ready'
    count = invoke.call_count
    with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == count


@pytest.mark.parametrize('scenario', ['invalid', 'truncated', 'missing_finish', 'budget'])
def test_failed_declaration_cannot_start_initialization_or_retry(scenario):
    record, invoke, run = setup()
    calls = list(invoke.side_effect)
    if scenario == 'budget': calls[1] = BudgetExhaustedError('tokens', 100001, 100000)
    elif scenario == 'invalid': calls[1]['content'] = '{}'
    elif scenario == 'truncated': calls[1]['finishReason'] = 'length'
    else: calls[1].pop('finishReason')
    invoke.side_effect = calls
    if scenario == 'budget': assert run() is None
    else:
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count == 2
    count = invoke.call_count
    if scenario == 'budget': assert run() is None
    else:
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count == count


@pytest.mark.parametrize('node', ['synthesize', 'plan_workflow_meta', stage.NODE])
def test_binding_option_cannot_be_injected_into_other_nodes(node):
    record, _, _ = setup()
    with pytest.raises(ValueError): options_for_record(record,node,{stage.OPTION:'baseline'})


def test_exact_schema_overhead_target_binding_and_provider_control_removal():
    record, invoke, run = setup(); run()
    options = {TARGET_OPTION:'baseline',stage.OPTION:'baseline'}
    from services.deep_research.runtime import research_model_options
    actual = options_for_record(record,INIT,research_model_options(INIT,options))
    fmt = actual['response_format']
    expected = len(json.dumps({'_deepseek_api':'responses','response_format':fmt},
        ensure_ascii=False,separators=(',',':')).encode())
    assert overhead_bytes(record,INIT,options) == expected
    from llm.responses_transport import payload
    wire = payload([{'role':'user','content':'fixture'}],actual,model='fixture',temperature=0)
    assert stage.OPTION not in wire and wire['stream'] is False
    for bad in ({TARGET_OPTION:'component',stage.OPTION:'baseline'},
                {TARGET_OPTION:'component',stage.OPTION:'missing'}, {TARGET_OPTION:'baseline'}):
        with pytest.raises(ValueError):options_for_record(record,INIT,bad)


def test_capacity_failure_keeps_complete_input_and_makes_zero_calls():
    record, _, _ = setup()
    metadata = {'baselineMode':'train','components':[], 'phases':[]}
    saved = []
    invoke = Mock()
    def run(existing=None):
        return stage.prepare(record,source_data=json.dumps({'question':'x'*40000}),metadata=metadata,
            aliases={},existing=existing,invoke=invoke,checkpoint=lambda value:saved.append(deepcopy(value)))
    with pytest.raises(DeepResearchError):run()
    assert saved[-1]['status'] == 'not_started_capacity'
    assert 'x'*40000 in saved[-1]['request']['prompt']
    with pytest.raises(DeepResearchError):run(saved[-1])
    invoke.assert_not_called()


def test_response_received_checkpoint_can_resume_without_another_call():
    from test_deep_research_workflow_representation import fixture
    value, metadata, aliases, _ = fixture()
    metadata['phases'] = []
    record = {**previous.record(), stage.MARKER:1}
    invoke = Mock(return_value={'content':json.dumps(value), 'finishReason':'stop'})
    saved = []
    def interrupt(value):
        saved.append(deepcopy(value))
        if value['status'] == 'response_received': raise RuntimeError('fixture interruption after durable receipt')
    kwargs = dict(record=record,source_data='{}',metadata=metadata,aliases=aliases,invoke=invoke)
    with pytest.raises(RuntimeError):stage.prepare(**kwargs,existing=None,checkpoint=interrupt)
    assert invoke.call_count == 1
    result = stage.prepare(**kwargs,existing=saved[-1],checkpoint=lambda v:saved.append(deepcopy(v)))
    assert result['status'] == 'ready' and invoke.call_count == 1


@pytest.mark.parametrize('node', [stage.NODE, INIT])
@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_actual_provider_payload_ledger_identity_capacity_and_unknown_no_resend(tmp_path, monkeypatch, node, scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.experiment_planning import request_identity
    from services.deep_research.contracts import UnknownCallError, UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    record, _, run = setup(); run()
    record.update(runId='r',taskId='t')
    repo = DeepResearchRepository(tmp_path/'calls.sqlite3'); repo.initialize(); repo.create_run(record); repo.begin_execution('r')
    post = Mock(side_effect=requests.ReadTimeout('fixture unknown')) if scenario == 'unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post',post)
    client = ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')).for_run('r')
    reserve = Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario == 'budget' else Mock(wraps=repo.reserve_call)
    tracked = TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    options = {TARGET_OPTION:'baseline',stage.OPTION:'baseline'} if node == INIT else {}
    request = request_identity(record,node,'x'*(32000-overhead_bytes(record,node,options)),options)
    def call():return tracked('r',node,request['prompt'],dispatch_options(record,node,request['extra']),use_reserve=True)
    if scenario == 'budget':
        with pytest.raises(BudgetExhaustedError):call()
        post.assert_not_called();return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError):call()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):call()
    else:call()
    assert post.call_count == 1 and repo.list_calls('r')[0]['argsDigest'] == digest(request)
    wire = post.call_args.kwargs['json']
    assert stage.OPTION not in wire and wire['stream'] is False and wire['max_output_tokens'] == 6144
    version=str(record[stage.MARKER])
    assert wire['text']['format']['name'] == ('workflow_init_representation_v'+version+'_baseline' if node == INIT else 'workflow_representation_v'+version)
    assert post.call_args.kwargs['timeout'] == 90
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == 32000+1024+6144
    with pytest.raises(ValueError,match='Prompt too large'):
        tracked('r',node,request['prompt']+'x',dispatch_options(record,node,request['extra']),use_reserve=True)
    assert post.call_count == 1


def test_feature_is_server_disabled_and_immutable_including_old_records(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path/'profiles.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_ = facade.create({'workspaceTaskId':'t','operationKey':'new','question':'Design','deferStart':True,
            stage.MARKER:1},start_async=False)
        assert row[stage.MARKER] == 0 and not stage.enabled(row)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(row['runId'],lambda r:{**r,stage.MARKER:1})
        old = deepcopy(row); old.update(runId='old',idempotencyKey='old'); old.pop(stage.MARKER); repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,stage.MARKER:1})
    finally:facade.shutdown()


def test_static_projection_preserves_all_exact_actions_parameters_and_output_identities():
    from test_deep_research_workflow_lifecycle_units import fixtures
    _, metadata, _ = fixtures()
    before = deepcopy(metadata)
    view = stage.type_context(metadata)
    assert metadata == before
    actions = []
    for phase in metadata['phases']:
        if phase['action'] not in actions:actions.append(phase['action'])
    assert [r['action'] for r in view['operationRequirements']] == actions
    for requirement in view['operationRequirements']:
        expected = []
        for phase in metadata['phases']:
            if phase['action'] != requirement['action']:continue
            for ref in [*phase['updates'], *[r['state'] for r in phase['reads'] if 'state' in r]]:
                if ref not in expected:expected.append(ref)
        assert requirement['componentRefs'] == expected
    assert view['outputInterfaces'] == [{k:p[k] for k in ('phaseId','outputs')}
                                        for p in metadata['phases'] if p['outputs']]
    assert view['binding']['metadataDigest'] == digest(metadata)
    assert view['components'] == metadata['components']
    assert 'phases' not in view  # This view does not grant execution order/availability.


def test_static_view_omissions_cannot_change_full_parent_identity_and_replay():
    record, _, _ = setup()
    from test_deep_research_workflow_lifecycle_units import fixtures
    _, metadata, _ = fixtures()
    record['budget'] = {'maxWallClockSeconds':0}
    saved=[]; invoke=Mock()
    stage.prepare(record,source_data='{}',metadata=metadata,aliases={},existing=None,
                  invoke=invoke,checkpoint=saved.append)
    assert saved[-1]['status'] == 'not_started_budget'
    changed=deepcopy(metadata)
    changed['phases'][0]['scope']='per_frame' if metadata['phases'][0]['scope'] != 'per_frame' else 'per_repeat'
    assert changed != metadata
    with pytest.raises(DeepResearchError):
        stage.prepare(record,source_data='{}',metadata=changed,aliases={},existing=saved[-1],
                      invoke=invoke,checkpoint=saved.append)
    invoke.assert_not_called()
