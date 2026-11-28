"""Typed-step representation proof; no model generation/scientific acceptance."""
from copy import deepcopy
import json
import pytest

from services.deep_research.workflow_metadata_steps import decode, view, descriptor, issues
from services.deep_research.workflow_metadata_ordered import decode as ordered_decode
from services.deep_research.workflow_units import unit_errors, META
from services.deep_research.workflow_lifecycle import _creation_point
from test_deep_research_workflow_metadata_ordered import authored


def primitives():
    old = authored(); ids = [p['phaseId'] for p in old['phases']]
    value = deepcopy(old); value['steps'] = value.pop('phases')
    for c in value['components']:
        life = c['lifecycle']; life['createBefore'] = ids.index(life['createBefore'])
        if life['disposeAfter'] is not None: life['disposeAfter'] = ids.index(life['disposeAfter'])
    for step in value['steps']:
        del step['phaseId']
        for read in step['reads']:
            if 'phaseId' in read:
                read['stepIndex'] = ids.index(read.pop('phaseId')); read['outputStage'] = 'operation'
    return value


def observations():
    value = primitives(); old = value['steps']
    def observe(measurement, recording):
        return {'scope': measurement['scope'], 'kind': 'observe', 'groups': deepcopy(measurement['groups']),
            'reads': deepcopy(measurement['reads']), 'measurement': deepcopy(measurement['action']),
            'outputs': deepcopy(measurement['outputs']), 'recording': {
                'inputs': [{k: deepcopy(r[k]) for k in ('outputId', 'selector')} for r in recording['reads'] if 'stepIndex' in r],
                'action': deepcopy(recording['action']), 'outputs': deepcopy(recording['outputs'])}}
    value['steps'] = old[:2] + [observe(old[2], old[4]), observe(old[3], old[5])]
    # This is an explicitly authored atomic schedule, not an old-run rewrite.
    value['components'][1]['lifecycle']['disposeAfter'] = 3
    return value


def test_all_existing_low_level_operations_and_boundaries_are_preserved():
    wire = primitives(); before = deepcopy(wire); old = ordered_decode(authored()); result = decode(wire)
    assert wire == before and not issues(wire)
    assert unit_errors(result, {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    for actual, original in zip(result['phases'], old['phases']):
        assert {k: v for k, v in actual.items() if k not in ('phaseId', 'reads')} == {
            k: v for k, v in original.items() if k not in ('phaseId', 'reads')}
        for read, old_read in zip(actual['reads'], original['reads']):
            assert read['selector'] == old_read['selector']
            if 'state' in old_read: assert read == old_read
            else:
                source_index = next(i for i, p in enumerate(old['phases']) if p['phaseId'] == old_read['phaseId'])
                assert read['outputId'] == old_read['outputId']
                assert read['phaseId'] == f'step_{source_index}_operation'
    for key in old.keys() - {'phases', 'components'}: assert result[key] == old[key]
    mapping = {p['phaseId']: (i, p) for i, p in enumerate(result['phases'])}
    original_mapping = {p['phaseId']: (i, p) for i, p in enumerate(old['phases'])}
    for actual, original in zip(result['components'], old['components']):
        assert actual['componentId'] == original['componentId'] and actual['appliesTo'] == original['appliesTo']
        assert _creation_point(actual['lifecycle'], mapping, 0) == _creation_point(original['lifecycle'], original_mapping, 0)


def test_observation_has_authored_measurement_and_save_with_unique_compiler_identity():
    wire = observations(); before = deepcopy(wire); result = decode(wire)
    assert wire == before and not issues(wire)
    assert unit_errors(result, {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    assert [p['kind'] for p in result['phases']] == ['fit', 'fit', 'evaluate', 'record', 'evaluate', 'record']
    ids = [p['phaseId'] for p in result['phases']]; assert len(ids) == len(set(ids))
    for step_index, phase_index in [(2, 2), (3, 4)]:
        step = wire['steps'][step_index]; measure, save = result['phases'][phase_index:phase_index+2]
        assert measure['action'] == step['measurement'] and save['action'] == step['recording']['action']
        assert measure['outputs'] == step['outputs'] and save['outputs'] == step['recording']['outputs']
        assert measure['groups'] == save['groups'] == step['groups']
        assert all(r['phaseId'] == measure['phaseId'] for r in save['reads'])
        assert measure['updates'] == save['updates'] == []
    assert result['components'][1]['lifecycle']['disposeAfter'] == 'step_3_record'


@pytest.mark.parametrize('invalid', [None, True, -1, 99, '2', 2.0])
def test_invalid_or_coercible_indices_are_never_selected_or_cast(invalid):
    wire = observations(); wire['components'][0]['lifecycle']['createBefore'] = invalid
    with pytest.raises(ValueError): decode(wire)
    assert any(i['code'] == 'steps.index' and i['actual'] == invalid for i in issues(wire))


@pytest.mark.parametrize('change', ['missing_selector', 'missing_output', 'new_output', 'missing_action', 'extra_update'])
def test_missing_observation_choices_are_not_filled_or_discarded(change):
    wire = observations(); step = wire['steps'][2]
    if change == 'missing_selector': del step['recording']['inputs'][0]['selector']
    elif change == 'missing_output': step['recording']['inputs'] = []
    elif change == 'new_output': step['recording']['inputs'][0]['outputId'] = 'not measured'
    elif change == 'missing_action': del step['recording']['action']
    else: step['updates'] = ['ntc']
    with pytest.raises(ValueError): decode(wire)


def test_future_output_and_group_leak_are_still_rejected_by_original_checks():
    wire = observations(); wire['steps'][0]['reads'].append({
        'stepIndex': 3, 'outputStage': 'record', 'outputId': wire['steps'][3]['recording']['outputs'][0], 'selector': 'chosen'})
    assert 'timeline.input.future_output' in unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    wire = observations(); wire['steps'][2]['reads'].append({'state': 'added', 'selector': 'treatment state'})
    assert 'timeline.input.group_leak' in unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)


def test_output_stage_is_explicit_and_primitive_schedules_remain_available():
    wire = observations(); wire['steps'][2]['reads'].append({
        'stepIndex': 0, 'outputStage': 'measurement', 'outputId': 'selected', 'selector': 'chosen'})
    with pytest.raises(ValueError): decode(wire)
    assert any(x['code'] == 'steps.output_stage' for x in issues(wire))
    assert decode(primitives())['phases'][2]['kind'] == 'evaluate'


def test_repeated_action_names_never_collide_and_wrong_lifetimes_are_not_repaired():
    wire = observations()
    for step in wire['steps'][2:]:
        step['measurement']['action'] = 'render_and_measure'
        step['recording']['action']['action'] = 'record_frame'
    result = decode(wire)
    assert len({p['phaseId'] for p in result['phases']}) == len(result['phases'])
    assert result['phases'][3]['action'] == result['phases'][5]['action']
    wire['components'][1]['lifecycle']['disposeAfter'] = 1
    assert 'timeline.input.after_disposal' in unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)


def test_fit_caps_missing_evaluation_and_frame_boundary_guards_are_unchanged():
    wire = primitives(); wire['steps'][0]['budget'] = None
    assert 'timeline.phase.budget' in unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    wire = primitives()
    for step in wire['steps']:
        if step['kind'] == 'evaluate': step['kind'] = 'record'
    assert 'timeline.evaluation.missing' in unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    wire = primitives(); wire['steps'][0]['scope'] = 'per_repeat'
    wire['components'][1]['lifecycle']['createBefore'] = 0
    with pytest.raises(ValueError): decode(wire)


def test_schema_does_not_ask_for_free_phase_names_or_implicit_record_operations():
    schema = descriptor(); text = json.dumps(schema)
    assert schema['name'] == 'typed_workflow_steps_v1'
    assert 'phaseId' not in text and 'createAfter' not in text
    assert 'steps' in schema['schema']['required'] and 'phases' not in schema['schema']['required']
    observe = schema['schema']['$defs']['step']['anyOf'][0]['properties']
    assert {'measurement', 'recording'} <= set(observe)
    assert {'inputs', 'action', 'outputs'} == set(observe['recording']['properties'])


def test_expansion_never_truncates_to_fit_original_phase_limit():
    wire = observations(); observe = wire['steps'][2]
    wire['steps'] = [deepcopy(observe) for _ in range(65)]
    assert any(x['code'] == 'steps.capacity' for x in issues(wire))
    with pytest.raises(ValueError): decode(wire)


def test_compiled_ir_and_explicit_initializers_use_original_assembly_and_binding():
    from test_deep_research_workflow_lifecycle_units import fixtures, setup
    from test_deep_research_workflow5_contract import claims
    from services.deep_research.execution_workflow_blueprint import errors, bind
    meta = decode(observations()); old = authored(); _, _, initializers = fixtures()
    # New fixture references compiler identities explicitly. No old runtime is migrated.
    for unit in initializers:
        for item in unit['initialization']['inputs']:
            if 'phaseId' in item:
                index = next(i for i, p in enumerate(old['phases']) if p['phaseId'] == item['phaseId'])
                item['phaseId'] = f'step_{index}_operation'
    _, _, invoke, run = setup([meta, *initializers]); saved = run()
    assert saved['status'] == 'ready' and errors(saved['value'], {'E1': 'owned'}, version=7) == []
    assert not saved['scientificApproval']
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls
    rows = claims(); rows[-1].pop('executionSpec')
    result, binding = bind({'claims': rows}, saved)
    assert result['claims'][-1]['executionSpec']['phases'] == meta['phases']
    assert not binding['scientificApproval']
