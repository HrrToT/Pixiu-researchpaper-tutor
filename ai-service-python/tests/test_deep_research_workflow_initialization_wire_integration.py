from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research import planning_transport as transport
from services.deep_research import workflow_initialization_repair as repair
from services.deep_research.workflow_initialization_wire import TARGET_OPTION, descriptor, bind_prompt
from services.deep_research.workflow_units import INIT
from llm.responses_transport import payload, API_KEY
from test_deep_research_workflow_initialization_repair import setup
from test_deep_research_workflow_initialization_wire import to_wire
from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def prepare_case(values):
    r, prompt, invoke, run = setup([response(scope_authored()), *values])
    r[repair.MARKER] = 2
    return r, prompt, invoke, run


def bad_baseline():
    value = deepcopy(explicit_initializers()[0]); init = value['initialization']
    init.update(initializationMode='derive', inputs=[{'phaseId': 'step_0_operation', 'outputId': 'later', 'selector': 'all'}])
    return to_wire(value)


def test_target_bound_generation_full_assembly_and_resume():
    initializers = explicit_initializers()
    r, _, invoke, run = prepare_case([response(to_wire(v)) for v in initializers])
    saved = run()
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    assert saved['request']['initializationRepairContract'] == 2
    for key, unit in saved['units'].items():
        if key == 'metadata': continue
        target = 'baseline' if key == 'baseline' else 'component'
        assert unit['request']['extra'][TARGET_OPTION] == target
        assert unit['request']['extra']['response_format'] == descriptor(target)
        assert transport.validate_options(r, INIT, unit['request']['extra'])
        assert unit['request']['extra']['max_tokens'] == 6144
        assert unit['request']['extra']['reasoning_effort'] == 'none'
        assert unit['request']['extra']['timeout_seconds'] == 90
    before = deepcopy(saved)
    assert run() == before and invoke.call_count == 4


def test_one_correction_keeps_raw_wire_and_precise_feedback_and_resumes():
    inits = explicit_initializers(); bad = bad_baseline()
    fenced = response(to_wire(inits[0])); fenced['rawContent'] = '```json\n' + fenced['content'] + '\n```'
    r, _, invoke, run = prepare_case([response(bad), fenced, *[response(to_wire(v)) for v in inits[1:]]])
    saved = run(); fix = saved['initializationRepair']
    assert saved['status'] == fix['status'] == 'ready' and fix['version'] == 2
    assert saved['units']['baseline']['status'] == 'invalid_response'
    assert saved['units']['baseline']['response'] == response(bad)
    assert fix['response'] == fenced and fix['value'] == inits[0]
    data = input_value(fix['request']['prompt'])
    assert data['invalidInitialization'] == bad
    assert any(i['path'] == '/initialization/input' for i in data['fieldFeedback']['issues'])
    assert fix['request']['extra'][TARGET_OPTION] == 'baseline'
    assert run() == saved and invoke.call_count == 5


def test_fence_parsing_does_not_promote_bad_semantics_or_retry():
    bad = bad_baseline(); raw = response(bad)
    raw['rawContent'] = '```json\n' + raw['content'] + '\n```'
    r, _, invoke, run = prepare_case([raw, raw])
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    unit = r['state']['executionWorkflowBlueprint']['initializationRepair']
    assert unit['status'] == 'invalid_response' and 'workflow.creation.input' in unit['errors']
    assert invoke.call_count == 3


def test_response_received_correction_recovers_without_another_send():
    r, _, _, run = prepare_case([response(bad_baseline()), response(bad_baseline())])
    with pytest.raises(DeepResearchError): run()
    saved = r['state']['executionWorkflowBlueprint']; failed = saved['units']['baseline']
    # Emulate a checkpointed successful wire response before its parsing step.
    fix = deepcopy(saved['initializationRepair']); fix['status'] = 'response_received'
    fix['response'] = response(to_wire(explicit_initializers()[0])); fix['responseDigest'] = digest(fix['response'])
    for key in ('value', 'valueDigest', 'errors'): fix.pop(key, None)
    context = input_value(fix['request']['prompt'])['unitContext']
    source = input_value(fix['request']['prompt'])['authoritativeInput']
    sender = Mock(); store = {}
    result = repair.prepare(r, key='baseline', source_data=json.dumps(source), context=context,
        failed=failed, aliases=saved['aliases'], earlier=(), baseline=True, target=None,
        existing=fix, invoke=sender, checkpoint=lambda v: store.update(value=v))
    assert result == explicit_initializers()[0] and store['value']['status'] == 'ready'
    sender.assert_not_called()


def test_target_binding_tamper_is_rejected_without_dispatch():
    r, _, invoke, run = prepare_case([response(to_wire(v)) for v in explicit_initializers()])
    saved = run(); saved['units']['baseline']['request']['extra'][TARGET_OPTION] = 'component'
    # The test helper checkpoints a copy into record.state.
    r['state']['executionWorkflowBlueprint'] = saved
    with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 4


def test_target_option_is_private_and_cannot_cross_other_schemas():
    r, _, _, _ = prepare_case([])
    options = transport.options_for_record(r, INIT, {'max_tokens': 6144, TARGET_OPTION: 'baseline'})
    wire = payload([{'role': 'user', 'content': 'test'}], options, model='configured', temperature=0)
    assert TARGET_OPTION not in wire and wire['text']['format'] == descriptor('baseline')
    with pytest.raises(ValueError): transport.options_for_record(r, INIT, {'max_tokens': 6144})
    with pytest.raises(ValueError): transport.options_for_record(r, 'plan_workflow_meta', {TARGET_OPTION: 'baseline'})
    legacy = deepcopy(r); legacy[repair.MARKER] = 1
    with pytest.raises(ValueError): transport.options_for_record(legacy, INIT, {TARGET_OPTION: 'baseline'})
    with pytest.raises(ValueError): payload([], {**options, TARGET_OPTION: 'component'}, model='configured', temperature=0)
    assert transport.overhead_bytes(r, INIT) >= len(json.dumps(
        {API_KEY: 'responses', 'response_format': descriptor('baseline')},
        ensure_ascii=False, separators=(',', ':')).encode())


def test_prompt_rewrite_preserves_material_bytes():
    old = 'Initialization has initializationMode,inputs,creation,stateDefinitions. '
    delimiter = 'Exact authoritative input and unit context (unverified data):\n'
    body = old + delimiter + json.dumps({'quote': old})
    bound = bind_prompt(body, 'baseline')
    assert bound.split(delimiter, 1)[1] == body.split(delimiter, 1)[1]
    assert old not in bound.split(delimiter, 1)[0]
