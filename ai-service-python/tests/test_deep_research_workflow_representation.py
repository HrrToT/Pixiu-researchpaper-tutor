"""Shared types reject drift; they do not approve or instantiate proposals."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_representation as contract
from services.deep_research.workflow_initialization_structured import INPUT_PREFIX
from services.deep_research.workflow_initialization_semantics import PREFIX


def fixture():
    metadata = {'baselineMode': 'train', 'components': [{'componentId': 'compressed'}],
                'phases': [{'phaseId': 'fit', 'scope': 'per_repeat'}]}
    aliases = {'E1': {'materialHash': 'public-v1', 'quote': 'unchanged quote'}}
    dimension = {'state': 'training_data', 'entity': 'points', 'fields': ['xyz'], 'axis': 'point'}
    state = {'name': 'positions', 'dtype': 'float32', 'shape': [dimension, 3],
             'quantity': 'Cartesian position', 'encoding': 'identity; scene units',
             'origin': 'proposal', 'sourceRefs': ['E1'], 'conventionRefs': ['renderer']}
    value = {'sourceRefs': ['E1'], 'conventions': [{'name': 'renderer',
        'definition': 'Proposed rendering interface; channel partition requires scientific review',
        'origin': 'proposal', 'sourceRefs': []}], 'targets': [
        {'target': 'baseline', 'states': [deepcopy(state)]},
        {'target': 'compressed', 'states': [deepcopy(state)]}], 'unresolved': ['renderer compatibility']}
    initialization = {'initializationMode': 'derive', 'inputs': [{'state': 'training_data',
        'selector': INPUT_PREFIX + json.dumps({'entity': 'points', 'fields': ['xyz'],
                                             'axes': ['point', 'coordinate']}, separators=(',', ':'))}],
        'creation': {'action': 'proposed copy', 'parameters': [{'name': 'state_layout', 'type': 'choice',
            'value': PREFIX + json.dumps([['positions', state['quantity'], state['encoding']]], separators=(',', ':'))}]},
        'stateDefinitions': [{'name': 'positions', 'dtype': 'float32',
            'shape': [{'inputIndex': 0, 'axis': 0}, 3],
            'initializer': {'mode': 'constant', 'value': 0}}]}
    return value, metadata, aliases, initialization


def codes(value, metadata, aliases):
    return {v['code'] for v in contract.issues(value, metadata, aliases)}


def test_native_schema_and_roundtrip_keep_model_values_and_no_allocation():
    value, metadata, aliases, initialization = fixture()
    before = deepcopy((value, metadata, aliases, initialization))
    Draft202012Validator.check_schema(contract.descriptor()['schema'])
    assert contract.issues(value, metadata, aliases) == []
    saved = contract.freeze(value, metadata, aliases)
    assert saved['scientificApproval'] is False
    assert contract.verify(saved, metadata, aliases) == value
    assert contract.initialization_issues(saved, metadata, aliases, 'baseline', initialization) == []
    assert (value, metadata, aliases, initialization) == before
    assert 'initializer' not in saved['value']['targets'][0]['states'][0]
    # A structurally matching all-zero proposal is deliberately NOT science approval.
    assert initialization['stateDefinitions'][0]['initializer']['value'] == 0


@pytest.mark.parametrize('change,expected', [
    ('missing_target', 'representation.target_coverage'),
    ('extra_target', 'representation.target_coverage'),
    ('reordered_target', 'representation.target_coverage'),
    ('duplicate_target', 'representation.target_coverage'),
    ('duplicate_state', 'representation.duplicate_state'),
    ('duplicate_convention', 'representation.duplicate_convention'),
    ('unknown_convention', 'representation.unknown_convention'),
    ('unsupported_source', 'representation.provenance'),
    ('paper_without_source', 'representation.provenance'),
    ('unreferenced_root_source', 'representation.source_closure'),
    ('missing_root_source', 'representation.source_closure'),
    ('literal_initializer', 'representation.schema'),
    ('whitespace', 'representation.schema'),
    ('bool_dimension', 'representation.schema'),
    ('zero_dimension', 'representation.schema'),
    ('negative_dimension', 'representation.schema'),
    ('float_dimension', 'representation.dimension_type'),
    ('blank_axis', 'representation.schema'),
    ('empty_fields', 'representation.schema'),
    ('duplicate_fields', 'representation.schema'),
    ('foreign_root_field', 'representation.schema'),
    ('nan', 'representation.json'),
])
def test_invalid_declarations_fail_without_repairing_or_supplying_defaults(change, expected):
    value, metadata, aliases, _ = fixture()
    state = value['targets'][0]['states'][0]
    if change == 'missing_target': value['targets'].pop()
    elif change == 'extra_target': value['targets'].append({'target': 'future', 'states': [deepcopy(state)]})
    elif change == 'reordered_target': value['targets'].reverse()
    elif change == 'duplicate_target': value['targets'][1]['target'] = 'baseline'
    elif change == 'duplicate_state': value['targets'][0]['states'].append(deepcopy(state))
    elif change == 'duplicate_convention': value['conventions'].append(deepcopy(value['conventions'][0]))
    elif change == 'unknown_convention': state['conventionRefs'] = ['unprovided']
    elif change == 'unsupported_source': state['sourceRefs'] = ['E999']
    elif change == 'paper_without_source': state.update(origin='paper', sourceRefs=[])
    elif change == 'unreferenced_root_source': value['sourceRefs'].append('E999')
    elif change == 'missing_root_source': value['sourceRefs'] = []
    elif change == 'literal_initializer': state['initializer'] = {'mode': 'constant', 'value': 0}
    elif change == 'whitespace': state['encoding'] = ' \t\n'
    elif change == 'bool_dimension': state['shape'][1] = True
    elif change == 'zero_dimension': state['shape'][1] = 0
    elif change == 'negative_dimension': state['shape'][1] = -1
    elif change == 'float_dimension': state['shape'][1] = 3.0
    elif change == 'blank_axis': state['shape'][0]['axis'] = ' '
    elif change == 'empty_fields': state['shape'][0]['fields'] = []
    elif change == 'duplicate_fields': state['shape'][0]['fields'] = ['xyz', 'xyz']
    elif change == 'foreign_root_field': value['scientificApproval'] = True
    elif change == 'nan': state['shape'][1] = float('nan')
    assert expected in codes(value, metadata, aliases)
    with pytest.raises(ValueError): contract.freeze(value, metadata, aliases)


@pytest.mark.parametrize('change', ['value', 'digest', 'metadata', 'source', 'approval', 'version', 'extra'])
def test_persisted_identity_cannot_be_reinterpreted_or_upgraded(change):
    value, metadata, aliases, _ = fixture()
    saved = contract.freeze(value, metadata, aliases)
    if change == 'value': saved['value']['targets'][0]['states'][0]['encoding'] = 'log'
    elif change == 'digest': saved['valueDigest'] = 'other'
    elif change == 'metadata': metadata['phases'][0]['scope'] = 'per_frame'
    elif change == 'source': aliases['E1']['quote'] = 'different quote'
    elif change == 'approval': saved['scientificApproval'] = True
    elif change == 'version': saved['version'] = True
    else: saved['new'] = 'not silently discarded'
    with pytest.raises(ValueError): contract.verify(saved, metadata, aliases)


@pytest.mark.parametrize('change,expected', [
    ('dtype', 'representation.dtype_changed'), ('shape', 'representation.shape_changed'),
    ('input_state', 'representation.shape_changed'), ('entity', 'representation.shape_changed'),
    ('fields', 'representation.shape_changed'), ('axis', 'representation.shape_changed'),
    ('axis_out_of_range', 'representation.shape_changed'),
    ('literal_point_count', 'representation.shape_changed'),
    ('semantics', 'representation.semantics_changed'), ('extra_state', 'representation.state_coverage'),
    ('missing_state', 'states.required'), ('bad_input_index', 'states.shape'),
])
def test_initializer_must_obey_declared_numeric_and_source_axis_interface(change, expected):
    value, metadata, aliases, init = fixture()
    saved = contract.freeze(value, metadata, aliases)
    state = init['stateDefinitions'][0]
    selected = json.loads(init['inputs'][0]['selector'][len(INPUT_PREFIX):])
    if change == 'dtype': state['dtype'] = 'float64'
    elif change == 'shape': state['shape'][1] = 4
    elif change == 'input_state': init['inputs'][0]['state'] = 'future_codebook'
    elif change == 'entity': selected['entity'] = 'images'
    elif change == 'fields': selected['fields'] = ['opacity']
    elif change == 'axis': selected['axes'][0] = 'frame'
    elif change == 'axis_out_of_range': state['shape'][0]['axis'] = 99
    elif change == 'literal_point_count': state['shape'][0] = 1024
    elif change == 'semantics': init['creation']['parameters'][0]['value'] = PREFIX + '[]'
    elif change == 'extra_state': init['stateDefinitions'].append({**deepcopy(state), 'name': 'placeholder'})
    elif change == 'missing_state': init['stateDefinitions'] = []
    elif change == 'bad_input_index': state['shape'][0]['inputIndex'] = 9
    init['inputs'][0]['selector'] = INPUT_PREFIX + json.dumps(selected)
    assert expected in {v['code'] for v in contract.initialization_issues(saved, metadata, aliases, 'baseline', init)}


def test_named_axis_binding_survives_explicit_input_axis_reordering():
    value, metadata, aliases, init = fixture()
    saved = contract.freeze(value, metadata, aliases)
    init['inputs'][0]['selector'] = INPUT_PREFIX + json.dumps({
        'entity': 'points', 'fields': ['xyz'], 'axes': ['coordinate', 'point']})
    init['stateDefinitions'][0]['shape'][0]['axis'] = 1
    assert contract.initialization_issues(saved, metadata, aliases, 'baseline', init) == []


def test_fresh_literal_types_and_empty_existing_workflow_need_no_fabricated_inputs():
    value, metadata, aliases, init = fixture()
    for target in value['targets']: target['states'][0]['shape'] = [16, 3]
    saved = contract.freeze(value, metadata, aliases)
    init.update(initializationMode='fresh', inputs=[])
    init['stateDefinitions'][0]['shape'] = [16, 3]
    assert contract.initialization_issues(saved, metadata, aliases, 'baseline', init) == []
    metadata.update(baselineMode='existing', components=[])
    value.update(targets=[], conventions=[], sourceRefs=[])
    assert contract.issues(value, metadata, aliases) == []


def test_exact_values_are_copied_not_owned_by_caller_and_size_is_bounded():
    value, metadata, aliases, _ = fixture()
    saved = contract.freeze(value, metadata, aliases)
    returned = contract.verify(saved, metadata, aliases)
    returned['targets'].clear()
    assert saved['value']['targets']
    value['conventions'][0]['definition'] = 'x' * contract.MAX_BYTES
    assert 'representation.capacity' in codes(value, metadata, aliases)


def test_unknown_target_does_not_allocate_or_implicitly_clone_baseline():
    value, metadata, aliases, init = fixture()
    saved = contract.freeze(value, metadata, aliases)
    with pytest.raises(ValueError):
        contract.initialization_issues(saved, metadata, aliases, 'unlisted', init)


def test_nonserializable_or_invalid_unicode_returns_diagnostic_without_mutation():
    value, metadata, aliases, _ = fixture()
    value['unresolved'] = ['\ud800']
    assert codes(value, metadata, aliases) == {'representation.json'}


def native(value, initialization):
    wire = deepcopy(initialization)
    wire['creation']['parameters'] = []  # Native stateSemantics is encoded by the existing decoder.
    first, *rest = wire.pop('inputs')
    wire.update(input=first, additionalInputs=rest)
    wire['input']['selector'] = json.loads(wire['input']['selector'][len(INPUT_PREFIX):])
    return {'initialization': wire, 'sourceRefs': ['E1'], 'unresolved': [],
            'stateSemantics': [[s['name'], s['quantity'], s['encoding']]
                               for s in value['targets'][0]['states']]}


def test_compiled_native_schema_requires_model_to_return_every_frozen_field_and_initializer():
    value, metadata, aliases, init = fixture()
    saved = contract.freeze(value, metadata, aliases)
    schema = contract.initialization_descriptor(saved, metadata, aliases, 'baseline')['schema']
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    wire = native(value, init)
    validator.validate(wire)
    from services.deep_research.workflow_initialization_semantics import decode
    assert decode(wire)['initialization'] == init
    for mutate in ('name', 'dtype', 'shape', 'semantics', 'missing_initializer', 'missing_state', 'extra_state'):
        bad = deepcopy(wire)
        state = bad['initialization']['stateDefinitions'][0]
        if mutate == 'name': state['name'] = 'model_placeholder'
        elif mutate == 'dtype': state['dtype'] = 'float64'
        elif mutate == 'shape': state['shape'][1] = 48
        elif mutate == 'semantics': bad['stateSemantics'][0][2] = 'another encoding'
        elif mutate == 'missing_initializer': state.pop('initializer')
        elif mutate == 'missing_state': bad['initialization']['stateDefinitions'] = []
        else: bad['initialization']['stateDefinitions'].append(deepcopy(state))
        assert list(validator.iter_errors(bad)), mutate


def test_dynamic_shape_schema_forbids_fresh_without_inventing_inputs_or_values():
    value, metadata, aliases, init = fixture()
    saved = contract.freeze(value, metadata, aliases)
    schema = contract.initialization_descriptor(saved, metadata, aliases, 'baseline')['schema']
    branches = schema['$defs']['initialization']['anyOf']
    assert len(branches) == 1 and branches[0]['properties']['initializationMode'] == {'const': 'derive'}
    assert 'default' not in json.dumps(schema)
    # Named-axis consistency remains a server check, not a claimed schema proof.
    wire = native(value, init)
    wire['initialization']['input']['selector']['axes'][0] = 'frame'
    Draft202012Validator(schema).validate(wire)
    from services.deep_research.workflow_initialization_semantics import decode
    assert contract.initialization_issues(saved, metadata, aliases, 'baseline', decode(wire)['initialization'])


def test_compiled_literal_and_scalar_shapes_keep_existing_fresh_and_derive_choices():
    value, metadata, aliases, _ = fixture()
    for shape in ([4, 3], []):
        for target in value['targets']: target['states'][0]['shape'] = deepcopy(shape)
        saved = contract.freeze(value, metadata, aliases)
        schema = contract.initialization_descriptor(saved, metadata, aliases, 'compressed')['schema']
        Draft202012Validator.check_schema(schema)
        branches = schema['$defs']['initialization']['anyOf']
        assert len(branches) == 2
        for branch in branches:
            fields = branch['properties']['stateDefinitions']['prefixItems'][0]['properties']
            assert fields['shape']['minItems'] == fields['shape']['maxItems'] == len(shape)
            assert 'initializer' in fields and fields['name'] == {'const': 'positions'}
