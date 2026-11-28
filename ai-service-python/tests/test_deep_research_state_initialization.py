from copy import deepcopy

import pytest

from services.deep_research.state_initialization import state_definition_errors, state_definitions_text


def definitions():
    return [{'name': 'weights', 'dtype': 'float32', 'shape': [4, 2],
        'initializer': {'mode': 'normal', 'mean': 0, 'std': .01, 'rng': 'Explicit fixture RNG', 'seed': {'mode': 'data_seed'}}},
        {'name': 'bias', 'dtype': 'float32', 'shape': [2], 'initializer': {'mode': 'constant', 'value': 0}}]


def test_defined_state_values_and_rng_survive_readable_rendering_without_execution():
    states = definitions()
    before = deepcopy(states)
    assert state_definition_errors(states, []) == []
    text = state_definitions_text(states)
    for expected in ['weights', 'float32', '4×2', '均值0', '标准差0.01', '当前数据种子', 'bias', '常量 0']:
        assert expected in text
    assert states == before


@pytest.mark.parametrize('change', ['absent_states', 'absent_initializer', 'shape_only', 'duplicate_name',
    'zero_dimension', 'boolean_dimension', 'unbound_dimension', 'negative_axis', 'boolean_axis',
    'missing_input_axis', 'zero_std', 'boolean_mean', 'negative_seed', 'boolean_seed', 'unknown_seed',
    'nonfinite_constant', 'huge_numeric_constant', 'wrong_constant_shape', 'ragged_constant',
    'string_for_float', 'empty_literal', 'extra_initializer_field', 'empty_dtype', 'missing_rng'])
def test_missing_values_invalid_distributions_and_shapes_are_rejected(change):
    states = definitions()
    s = states[0]
    if change == 'absent_states': states = []
    elif change == 'absent_initializer': s.pop('initializer')
    elif change == 'shape_only': s['initializer'] = {'mode': 'constant'}
    elif change == 'duplicate_name': states[1]['name'] = s['name']
    elif change == 'zero_dimension': s['shape'] = [0, 2]
    elif change == 'boolean_dimension': s['shape'] = [True, 2]
    elif change == 'unbound_dimension': s['shape'] = ['N', 2]
    elif change == 'negative_axis': s['shape'] = [{'inputIndex': 0, 'axis': -1}, 2]
    elif change == 'boolean_axis': s['shape'] = [{'inputIndex': 0, 'axis': True}, 2]
    elif change == 'missing_input_axis': s['shape'] = [{'inputIndex': 1, 'axis': 0}, 2]
    elif change == 'zero_std': s['initializer']['std'] = 0
    elif change == 'boolean_mean': s['initializer']['mean'] = False
    elif change == 'negative_seed': s['initializer']['seed'] = {'mode': 'fixed', 'value': -1}
    elif change == 'boolean_seed': s['initializer']['seed'] = {'mode': 'fixed', 'value': True}
    elif change == 'unknown_seed': s['initializer']['seed'] = {'mode': 'choose_later'}
    elif change == 'nonfinite_constant': s['initializer'] = {'mode': 'constant', 'value': float('nan')}
    elif change == 'huge_numeric_constant': s['initializer'] = {'mode': 'constant', 'value': 10**400}
    elif change == 'wrong_constant_shape': s['initializer'] = {'mode': 'constant', 'value': [1, 2, 3]}
    elif change == 'ragged_constant': s['initializer'] = {'mode': 'constant', 'value': [[1], [2, 3]]}
    elif change == 'string_for_float': s['initializer'] = {'mode': 'constant', 'value': 'later'}
    elif change == 'empty_literal': s['initializer'] = {'mode': 'constant', 'value': []}
    elif change == 'extra_initializer_field': s['initializer']['default'] = 'unknown'
    elif change == 'empty_dtype': s['dtype'] = ''
    elif change == 'missing_rng': s['initializer'].pop('rng')
    assert state_definition_errors(states, [{'state': 'training_data', 'selector': 'training matrix'}])


@pytest.mark.parametrize('value', [False, -1, 2, {'inputIndex': 0}])
def test_operation_cannot_reference_an_unavailable_input(value):
    states = definitions()
    states[0]['initializer'] = {'mode': 'operation', 'inputIndices': [value],
        'rule': {'action': 'Clone selected weights.', 'parameters': [{'name': 'scale', 'type': 'number', 'value': .5}]}}
    assert 'states.operation_inputs' in state_definition_errors(states, [{'state': 'baseline', 'selector': 'weights'}])


def test_dynamic_shape_and_explicit_input_transformation_are_preserved():
    states = definitions()
    states[0]['shape'] = [{'inputIndex': 0, 'axis': 0}, 2]
    states[0]['initializer'] = {'mode': 'operation', 'inputIndices': [0],
        'rule': {'action': 'Clone the selected weight tensor and multiply by the proposed factor.',
            'parameters': [{'name': 'factor', 'type': 'number', 'value': .5}]}}
    inputs = [{'state': 'baseline', 'selector': 'trained weight tensor'}]
    assert state_definition_errors(states, inputs) == []
    assert '输入0的第0轴×2' in state_definitions_text(states)
    assert 'factor：0.5' in state_definitions_text(states)
    states[0]['initializer']['rule']['parameters'] = []
    assert 'states.operation_rule' in state_definition_errors(states, inputs)


def test_vector_constants_broadcast_but_do_not_allow_incompatible_tensor_sizes():
    s = {'name': 'rotation', 'dtype': 'float32', 'shape': [10000, 4],
         'initializer': {'mode': 'constant', 'value': [1, 0, 0, 0]}}
    assert state_definition_errors([s], []) == []
    s['initializer']['value'] = [[1, 0, 0, 0], [1, 0, 0, 0]]
    assert 'states.constant_shape' in state_definition_errors([s], [])


def test_uniform_bounds_and_actual_seed_are_validated():
    states = definitions()
    states[0]['initializer'] = {'mode': 'uniform', 'low': -1, 'high': 1,
        'rng': 'Explicit fixture RNG', 'seed': {'mode': 'fixed', 'value': 7}}
    assert state_definition_errors(states, []) == []
    assert '固定种子7' in state_definitions_text(states)
    states[0]['initializer']['low'] = 1
    assert 'states.distribution_parameters' in state_definition_errors(states, [])
