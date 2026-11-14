from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_metadata_bounded_schema as bounded
from services.deep_research import workflow_metadata_reference_context as previous
from services.deep_research.planning_transport import options_for_record
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response


def fixtures():
    basic = wire_value()
    setup = deepcopy(basic); setup['steps'][0].update(kind='setup', budget=None)
    shared = deepcopy(basic); step = shared['steps'][2]
    step.update(kind='evaluate_shared', groups=['0', '1'], sharing='shared'); step.pop('group')
    from test_deep_research_workflow_metadata_steps import observations
    from test_deep_research_workflow_metadata_single_group import authored
    from services.deep_research.workflow_metadata_scope_position import FIELD
    observed = authored(observations)
    for component in observed['components']:
        life = component['lifecycle']; life[FIELD] = life.pop('createBefore')
    for step in observed['steps']:
        if step['kind'] == 'evaluate': step['group'] = step.pop('groups')[0]
    return [basic, setup, shared, observed]


def test_standard_validator_all_step_kinds_keep_the_same_acceptance_boundary():
    old = Draft202012Validator(previous.descriptor()['schema'])
    schema = bounded.descriptor()['schema']; Draft202012Validator.check_schema(schema)
    new = Draft202012Validator(schema)
    kinds = set()
    for value in fixtures():
        assert old.is_valid(value) and new.is_valid(value)
        for i, step in enumerate(value['steps']):
            kinds.add(step['kind'])
            for field in step:
                missing = deepcopy(value); missing['steps'][i].pop(field)
                assert not old.is_valid(missing) and not new.is_valid(missing)
                for leaf in (None, False, {}, [], 0, ''):
                    mutated = deepcopy(value); mutated['steps'][i][field] = leaf
                    assert old.is_valid(mutated) == new.is_valid(mutated), (step['kind'], field, leaf)
            extra = deepcopy(value)
            extra['steps'][i]['extra'] = True
            assert not old.is_valid(extra) and not new.is_valid(extra)
            # Another branch's real field must still be forbidden here.
            field, data = ('updates', []) if step['kind'] == 'observe' else ('measurement', {'action': 'probe', 'parameters': []})
            extra['steps'][i].pop('extra'); extra['steps'][i][field] = data
            assert not old.is_valid(extra) and not new.is_valid(extra)
    assert kinds == {'fit', 'setup', 'evaluate', 'evaluate_shared', 'record', 'observe'}


def test_optional_or_open_branches_cannot_enter_the_closed_field_count_transform():
    for branch in ({'type': 'object', 'properties': {'x': {}}, 'required': [], 'additionalProperties': False},
                   {'type': 'object', 'properties': {'x': {}}, 'required': ['x'], 'additionalProperties': True}):
        with pytest.raises(ValueError): bounded.closed_branches([branch])


def test_existing_stricter_property_count_is_not_relaxed():
    branches = [{'type': 'object', 'properties': {'x': {'type': 'number'}},
                 'required': ['x'], 'additionalProperties': False, 'maxProperties': 0}]
    result = bounded.closed_branches(branches)
    assert not Draft202012Validator(result).is_valid({'x': 1})


def test_definition_aliases_escaped_names_and_literal_objects_are_preserved():
    literal = {'$ref': 'literal data, never resolved'}
    schema = {'type': 'object', 'properties': {'a': {'$ref': '#/$defs/alias'}},
        'const': literal, '$defs': {'alias': {'$ref': '#/$defs/a~1b'},
            'a/b': {'type': 'number'}, 'unused': {'type': 'string'}}}
    before = deepcopy(schema); new = bounded.normalize_definitions(schema)
    assert schema == before and new['const'] == literal and len(new['$defs']) == 1
    assert new['properties']['a']['$ref'] == '#/$defs/a'
    for value in ({'a': 1}, {'a': 'x'}, literal):
        assert Draft202012Validator(new).is_valid(value) == Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ValueError): bounded.normalize_definitions({'$defs': {'x': {'$ref': '#/$defs/x'}}})


def test_size_reduction_and_semantic_decoder_unchanged():
    size = lambda v: len(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode())
    assert size(previous.descriptor()) - size(bounded.descriptor()) >= 1000
    assert bounded.decode is previous.decode and bounded.field_feedback is previous.field_feedback


def test_complete_assembly_resume_and_native_role_limits():
    r, _, invoke, run = setup_repair([response(wire_value()), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=24, workflowInitializationOutputContractVersion=1)
    saved = run(); assert saved['status'] == 'ready' and run() == saved and invoke.call_count == 4
    for node in ('plan_workflow_meta', 'repair_workflow_meta'):
        options = options_for_record(r, node, {'temperature': 0.0})
        assert options['response_format'] == bounded.descriptor()
        assert options['max_tokens'] == 3072 and options['reasoning_effort'] == 'none'
