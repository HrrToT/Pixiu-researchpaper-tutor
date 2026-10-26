from copy import deepcopy
import pytest

from services.deep_research import workflow_metadata_evaluation_groups as grouped
from services.deep_research import workflow_metadata_fit_budget as legacy
from services.deep_research.workflow_metadata_scope_position import FIELD
from services.deep_research.workflow_units import unit_errors,META
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps import primitives


def wire_value():
    value=authored(primitives)
    for component in value['components']:
        life=component['lifecycle'];life[FIELD]=life.pop('createBefore')
    for step in value['steps']:
        if step['kind']=='evaluate':
            assert len(step['groups'])==1
            step['group']=step.pop('groups')[0]
    return value


def test_per_arm_evaluations_lower_without_choosing_groups_or_changing_operations():
    value=wire_value();before=deepcopy(value);lowered,issues=grouped.expanded(value)
    assert not issues and not grouped.coverage_issues(lowered)
    assert grouped.decode(value)==legacy.decode(lowered)
    assert unit_errors(grouped.decode(value),{'E1':'owned'},node=META,version=7,metadata_rows=True)==[]
    assert value==before


def test_shared_evaluation_remains_available_when_all_inputs_exist_for_every_arm():
    value=wire_value();step=value['steps'][2]
    step.update(kind='evaluate_shared',groups=['0','1'],sharing='shared');step.pop('group')
    assert unit_errors(grouped.decode(value),{'E1':'owned'},node=META,version=7,metadata_rows=True)==[]
    assert grouped.decode(value)['phases'][2]['kind']=='evaluate'


def test_shared_evaluation_cannot_read_treatment_state_for_control():
    value=wire_value();step=value['steps'][2]
    step.update(kind='evaluate_shared',groups=['0','1'],sharing='shared');step.pop('group')
    step['reads'].append({'state':'added','selector':'all'})
    assert any(i['code']=='timeline.input.group_leak' for i in grouped.field_feedback(value,{'E1':'owned'})['issues'])


def test_dropping_control_measurement_does_not_cure_a_group_leak():
    value=wire_value();value['steps'][2]['group']='1'
    before=deepcopy(value)
    with pytest.raises(ValueError):grouped.decode(value)
    issue=next(i for i in grouped.field_feedback(value,{'E1':'owned'})['issues'] if i['code']=='evaluation.coverage')
    assert issue['missingGroups']==['0'] and value==before


@pytest.mark.parametrize('kind,sharing', [('evaluate','shared'),('evaluate_shared','per_group')])
def test_kind_and_sharing_cannot_disagree(kind,sharing):
    value=wire_value();step=value['steps'][2]
    if kind=='evaluate_shared':step['groups']=[step.pop('group')]
    step.update(kind=kind,sharing=sharing)
    assert grouped.complete_scaffolding(value)
    with pytest.raises(ValueError):grouped.decode(value)
    assert any(i['code']=='evaluation.sharing' for i in grouped.field_feedback(value,{'E1':'owned'})['issues'])


def test_old_group_arrays_are_not_silently_split_or_chosen():
    value=wire_value();step=value['steps'][2];step['groups']=[step.pop('group')]
    before=deepcopy(value)
    with pytest.raises(ValueError):grouped.decode(value)
    assert not grouped.complete_scaffolding(value) and value==before


def test_schema_preserves_shared_evaluations_and_legacy_descriptor():
    old=legacy.descriptor();before=deepcopy(old);new=grouped.descriptor()
    branches=new['schema']['$defs']['step']['anyOf']
    single=next(b for b in branches if b['properties']['kind'].get('const')=='evaluate')
    shared=next(b for b in branches if b['properties']['kind'].get('const')=='evaluate_shared')
    assert 'group' in single['required'] and 'groups' not in single['properties']
    assert single['properties']['sharing']=={'const':'per_group'}
    assert 'groups' in shared['required'] and shared['properties']['sharing']=={'const':'shared'}
    assert legacy.descriptor()==before
