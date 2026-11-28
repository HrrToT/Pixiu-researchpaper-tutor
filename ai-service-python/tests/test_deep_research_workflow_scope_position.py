from copy import deepcopy
import pytest

from services.deep_research import workflow_metadata_scope_position as local
from services.deep_research import workflow_metadata_scope_end as legacy
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_single_group import authored


def wire_value():
    wire = authored()
    for component in wire['components']:
        life = component['lifecycle']
        life[local.FIELD] = life.pop('createBefore')
        life['disposeAfter'] = 'scope_end'
    return wire


def test_local_zero_after_repeat_preparation_means_first_frame_step():
    wire = wire_value(); wire['steps'][0]['scope'] = 'per_repeat'
    wire['components'][1]['lifecycle'][local.FIELD] = 0
    before = deepcopy(wire); lowered, issues = local.expanded(wire)
    assert not issues
    assert lowered['components'][0]['lifecycle']['createBefore'] == 0
    assert lowered['components'][1]['lifecycle']['createBefore'] == 1
    assert lowered['steps'] == wire['steps'] and wire == before
    assert unit_errors(local.decode(wire), {'E1':'owned'}, node=META, version=7, metadata_rows=True) == []


def test_later_position_preserves_dependency_and_original_full_assembly():
    from test_deep_research_workflow_lifecycle_units import setup
    from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
    from services.deep_research.execution_workflow_blueprint import errors
    wire = wire_value(); before = deepcopy(wire)
    meta = local.decode(wire)
    assert meta == legacy.decode(local.expanded(wire)[0])
    _, _, invoke, run = setup([meta, *explicit_initializers()])
    saved = run()
    assert saved['status'] == 'ready' and errors(saved['value'], {'E1':'owned'}, version=7) == []
    count = invoke.call_count
    assert run() == saved and invoke.call_count == count and wire == before
    assert not saved['scientificApproval']


@pytest.mark.parametrize('position', [-1, 99, True, 1.0, '0', None, 'scope_start'])
def test_invalid_position_is_not_coerced_or_given_a_fallback(position):
    wire = wire_value(); wire['components'][1]['lifecycle'][local.FIELD] = position
    before = deepcopy(wire)
    assert local.complete_scaffolding(wire)
    with pytest.raises(ValueError): local.decode(wire)
    issue = local.field_feedback(wire, {})['issues'][0]
    assert issue['actual'] == position and issue['path'].endswith('/'+local.FIELD)
    assert wire == before


@pytest.mark.parametrize('scope', ['per_frame', 'invented'])
def test_missing_frame_block_or_unknown_scope_is_not_invented(scope):
    wire = wire_value(); wire['components'][1]['lifecycle']['scope'] = scope
    for step in wire['steps']: step['scope'] = 'per_repeat'
    with pytest.raises(ValueError): local.decode(wire)
    issue = local.field_feedback(wire, {})['issues'][0]
    assert issue['availableGlobalStepIndices'] == []


def test_new_and_old_coordinate_fields_cannot_be_mixed_or_auto_imported():
    old = authored(); before = deepcopy(old)
    assert not local.complete_scaffolding(old)
    with pytest.raises(ValueError): local.decode(old)
    assert old == before
    wire = wire_value(); wire['components'][0]['lifecycle']['createBefore'] = 0
    assert not local.complete_scaffolding(wire)
    with pytest.raises(ValueError): local.decode(wire)


def test_future_results_and_cross_group_access_remain_rejected():
    wire = wire_value()
    wire['steps'][2]['reads'].append({'state':'added','selector':'treatment only'})
    assert any(i['code'] == 'timeline.input.group_leak' for i in local.field_feedback(wire, {'E1':'owned'})['issues'])
    wire = wire_value()
    wire['steps'][0]['reads'].append({'stepIndex':3,'outputStage':'record',
        'outputId':wire['steps'][3]['recording']['outputs'][0],'selector':'future'})
    assert 'timeline.input.future_output' in unit_errors(
        local.decode(wire), {'E1':'owned'}, node=META, version=7, metadata_rows=True)


def test_schema_has_one_unambiguous_position_field_and_preserves_legacy_schema():
    old = legacy.descriptor(frame_count_rules=True, compact_rules=True); before = deepcopy(old)
    schema = local.descriptor(); life = schema['schema']['$defs']['lifecycle']
    assert life['properties'][local.FIELD]['type'] == 'integer'
    assert local.FIELD in life['required'] and 'createBefore' not in life['properties']
    assert legacy.descriptor(frame_count_rules=True, compact_rules=True) == before
