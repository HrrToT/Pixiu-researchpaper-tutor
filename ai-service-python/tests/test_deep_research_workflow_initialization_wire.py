from copy import deepcopy
import json

import pytest

from services.deep_research.workflow_initialization_wire import descriptor, decode, parse, field_feedback
from services.deep_research.workflow_units import unit_errors, INIT
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers


def to_wire(value):
    wire = deepcopy(value); init = wire['initialization']
    if init['initializationMode'] == 'derive':
        inputs = init.pop('inputs'); init.update(input=inputs[0], additionalInputs=inputs[1:])
    for state in init['stateDefinitions']:
        initializer = state['initializer']
        if initializer['mode'] == 'operation':
            rule = initializer['rule']; params = rule.pop('parameters')
            rule.update(parameter=params[0], additionalParameters=params[1:])
    return wire


@pytest.mark.parametrize('index', [0, 1, 2])
def test_full_initializers_roundtrip_without_mutation(index):
    value = explicit_initializers()[index]; wire = to_wire(value); before = deepcopy(wire)
    assert decode(wire) == value and wire == before
    assert parse('```json\n' + json.dumps(wire) + '\n```') == value


def test_target_formats_differ_only_in_available_inputs_and_name():
    baseline = descriptor('baseline'); component = descriptor('component')
    assert baseline['schema']['$defs']['timelineInput']['properties']['state'] == {'const': 'training_data'}
    assert len(component['schema']['$defs']['timelineInput']['anyOf']) == 2
    a = deepcopy(baseline); b = deepcopy(component)
    a.pop('name'); b.pop('name')
    a['schema']['$defs'].pop('timelineInput'); b['schema']['$defs'].pop('timelineInput')
    assert a == b
    assert descriptor('component') == component
    with pytest.raises(ValueError): descriptor('unknown')


@pytest.mark.parametrize('raw', ['{"sourceRefs":[],"sourceRefs":[]}', '```json\n{}', '{} trailing', '{"a":NaN}'])
def test_no_duplicate_partial_or_nonfinite_salvage(raw):
    with pytest.raises(ValueError): parse(raw)


def test_order_and_shape_references_are_not_rewritten():
    value = explicit_initializers()[0]; init = value['initialization']
    init.update(initializationMode='derive', inputs=[{'state': 'training_data', 'selector': 'first'},
                                                   {'state': 'training_data', 'selector': 'second'}])
    init['stateDefinitions'][0]['shape'] = [{'inputIndex': 1, 'axis': 0}]
    assert decode(to_wire(value)) == value


def test_conflicting_layout_is_not_silently_dropped():
    wire = to_wire(explicit_initializers()[0]); init = wire['initialization']
    init.update(initializationMode='derive', input={'state': 'training_data', 'selector': 'all'}, additionalInputs=[])
    init['inputs'] = []
    with pytest.raises(ValueError): decode(wire)


def test_late_baseline_input_and_empty_rule_remain_semantically_invalid():
    value = explicit_initializers()[0]; init = value['initialization']
    init.update(initializationMode='derive', inputs=[{'phaseId': 'later', 'outputId': 'trained', 'selector': 'all'}])
    init['stateDefinitions'][0]['initializer'] = {
        'mode': 'operation', 'inputIndices': [0], 'rule': {'action': 'train', 'parameters': []}}
    before = deepcopy(value)
    errors = unit_errors(value, {'E1': 'owned'}, node=INIT, baseline=True, version=7)
    result = field_feedback(value, errors, target='baseline')
    paths = {i['path'] for i in result['issues']}
    assert '/initialization/input' in paths
    assert '/initialization/stateDefinitions/0/initializer/rule/parameter' in paths
    assert not result['scientificApproval'] and value == before and errors
    component = field_feedback(value, errors, target='component')
    assert '/initialization/input' not in {i['path'] for i in component['issues']}


def test_missing_first_parameter_is_rejected_and_invalid_leaf_is_retained():
    wire = to_wire(explicit_initializers()[0])
    wire['initialization']['stateDefinitions'][0]['initializer'] = {
        'mode': 'operation', 'inputIndices': [], 'rule': {'action': 'create', 'additionalParameters': []}}
    with pytest.raises(ValueError): decode(wire)
    wire['initialization']['stateDefinitions'][0]['initializer']['rule']['parameter'] = None
    result = decode(wire)
    assert result['initialization']['stateDefinitions'][0]['initializer']['rule']['parameters'] == [None]
    assert unit_errors(result, {'E1': 'owned'}, node=INIT, baseline=True, version=7)


def test_parameter_order_values_and_nonoperation_initializers_are_preserved():
    value = explicit_initializers()[0]
    state = value['initialization']['stateDefinitions'][0]
    state['initializer'] = {'mode': 'operation', 'inputIndices': [], 'rule': {
        'action': 'initialize', 'parameters': [
            {'name': 'method', 'type': 'choice', 'value': 'authored'},
            {'name': 'scale', 'type': 'number', 'value': 0.125}]}}
    wire = to_wire(value)
    assert decode(wire) == value
    assert wire['initialization']['stateDefinitions'][0]['initializer']['rule']['parameter']['name'] == 'method'
    wire['initialization']['stateDefinitions'][0]['initializer']['rule']['additionalParameters'][0]['value'] = float('inf')
    with pytest.raises(ValueError): decode(wire)


@pytest.mark.parametrize('replacement', [None, {}, 'remaining'])
def test_malformed_remaining_inputs_cannot_be_coerced(replacement):
    value = explicit_initializers()[0]
    value['initialization'].update(initializationMode='derive', inputs=[{'state': 'training_data', 'selector': 'all'}])
    wire = to_wire(value); wire['initialization']['additionalInputs'] = replacement
    with pytest.raises(ValueError): decode(wire)
