from copy import deepcopy
import pytest

from services.deep_research import workflow_metadata_single_group as scalar
from services.deep_research import workflow_metadata_steps as steps
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_steps import observations, primitives


def authored(factory=observations):
    wire = factory()
    for step in wire['steps']:
        if step['kind'] in scalar.SINGLE:
            assert len(step['groups']) == 1
            step['group'] = step.pop('groups')[0]
    return wire


@pytest.mark.parametrize('factory', [observations, primitives])
def test_scalar_preserves_all_original_operations_and_arm_choices(factory):
    original = factory(); wire = authored(factory); before = deepcopy(wire)
    assert scalar.expanded(wire) == original
    assert scalar.decode(wire) == steps.decode(original)
    assert unit_errors(scalar.decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    assert wire == before and scalar.complete_scaffolding(wire)


@pytest.mark.parametrize('group', ['', 'both', '0,1', ['0', '1'], 0, True, None])
def test_invalid_scalar_is_not_coerced_or_split_and_remains_available_for_feedback(group):
    wire = authored(); wire['steps'][2]['group'] = group; before = deepcopy(wire)
    assert scalar.complete_scaffolding(wire)
    with pytest.raises(ValueError): scalar.decode(wire)
    feedback = scalar.field_feedback(wire, {'E1': 'owned'})
    issue = next(x for x in feedback['issues'] if x['path'] == '/steps/2/group')
    assert issue['actual'] == group and not feedback['scientificApproval'] and wire == before


def test_arm_specific_state_cannot_leak_into_other_arm():
    wire = authored(); wire['steps'][2]['reads'].append({'state': 'added', 'selector': 'treatment only'})
    result = scalar.field_feedback(wire, {'E1': 'owned'})
    assert any(x['code'] == 'timeline.input.group_leak' for x in result['issues'])


def test_native_schema_uses_scalar_for_single_arm_and_arrays_for_shared_steps():
    schema = scalar.descriptor(); branches = schema['schema']['$defs']['step']['anyOf']
    for branch in branches:
        kind = branch['properties']['kind'].get('const')
        props = branch['properties']
        if kind in scalar.SINGLE:
            assert props['group']['type'] == 'string' and props['group']['pattern'] == '^[01]+$'
            assert 'groups' not in props and 'group' in branch['required']
        else: assert props['groups']['type'] == 'array' and 'group' not in props
    assert steps.descriptor()['name'] == 'typed_workflow_steps_v1'


def test_conflicting_old_and_new_ownership_is_rejected_without_choosing():
    wire = authored(); wire['steps'][2]['groups'] = ['1']
    assert not scalar.complete_scaffolding(wire)
    with pytest.raises(ValueError): scalar.decode(wire)
