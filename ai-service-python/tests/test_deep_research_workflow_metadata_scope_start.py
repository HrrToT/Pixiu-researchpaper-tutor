from copy import deepcopy
import pytest

from services.deep_research import workflow_metadata_scope_start as entrance
from services.deep_research import workflow_metadata_scope_end as release
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_single_group import authored


def test_exact_integer_allocations_and_legacy_schema_remain_unchanged():
    wire = authored(); original = deepcopy(wire); schema = release.descriptor()
    assert entrance.expanded(wire) == (wire, [])
    assert entrance.decode(wire) == release.decode(wire)
    assert wire == original
    assert 'scope_start' not in str(schema)
    assert release.descriptor() == schema


def test_authored_entrances_lower_to_scope_steps_without_mutating_input():
    wire = authored()
    for component in wire['components']:
        component['lifecycle'].update(createBefore='scope_start', disposeAfter='scope_end')
    before = deepcopy(wire); lowered, bounds = entrance.expanded(wire)
    assert len(bounds) == len(wire['components'])
    for component in lowered['components']:
        scope = component['lifecycle']['scope']
        assert component['lifecycle']['createBefore'] == (0 if scope == 'per_repeat' else next(
            i for i, step in enumerate(wire['steps']) if step['scope'] == scope))
    assert unit_errors(entrance.decode(wire), {'E1': 'owned'}, node=META,
                       version=7, metadata_rows=True) == []
    assert wire == before and lowered['steps'] == wire['steps']
    assert not entrance.field_feedback(wire, {'E1': 'owned'})['scientificApproval']


def test_wrong_explicit_index_is_not_automatically_moved():
    wire = authored(); wire['components'][1]['lifecycle']['createBefore'] = 0
    wire['steps'][0]['scope'] = 'per_repeat'
    assert entrance.expanded(wire)[0] == wire
    with pytest.raises(ValueError): entrance.decode(wire)
    issues = entrance.field_feedback(wire, {'E1': 'owned'})['issues']
    assert any(i['code'] == 'ordered.allocation' and i['actual'] == 0 for i in issues)


@pytest.mark.parametrize('scope', ['per_frame', 'invented'])
def test_missing_or_unknown_scope_cannot_create_an_entrance(scope):
    wire = authored(); wire['components'][1]['lifecycle'].update(
        scope=scope, createBefore='scope_start')
    for step in wire['steps']:
        step['scope'] = 'per_repeat' if scope == 'per_frame' else 'per_frame'
    with pytest.raises(ValueError): entrance.decode(wire)
    assert not entrance.complete_scaffolding(wire)


def test_scope_start_does_not_allow_cross_arm_reads():
    wire = authored(); wire['components'][1]['lifecycle'].update(
        createBefore='scope_start', disposeAfter='scope_end')
    wire['steps'][2]['reads'].append({'state': 'added', 'selector': 'treatment only'})
    assert any(i['code'] == 'timeline.input.group_leak'
               for i in entrance.field_feedback(wire, {'E1': 'owned'})['issues'])


def test_schema_keeps_exact_later_allocations_available():
    schema = entrance.descriptor()
    branches = schema['schema']['$defs']['lifecycle']['properties']['createBefore']['anyOf']
    assert {'const': 'scope_start'} in branches
    assert any(b.get('type') == 'integer' for b in branches)
    wire = authored(); wire['components'][1]['lifecycle']['createBefore'] = 1
    assert entrance.expanded(wire)[0]['components'][1]['lifecycle']['createBefore'] == 1


def test_entrance_allocation_cannot_make_future_measurements_available():
    wire = authored()
    wire['components'][1]['lifecycle'].update(createBefore='scope_start', disposeAfter='scope_end')
    wire['steps'][0]['reads'].append({
        'stepIndex': 3, 'outputStage': 'record',
        'outputId': wire['steps'][3]['recording']['outputs'][0], 'selector': 'future result'})
    assert 'timeline.input.future_output' in unit_errors(
        entrance.decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)


def test_full_assembly_and_binding_keep_original_scientific_checks():
    from test_deep_research_workflow_lifecycle_units import setup
    from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
    from test_deep_research_workflow5_contract import claims
    from services.deep_research.execution_workflow_blueprint import errors, bind
    wire = authored()
    # The added component's initializer consumes an earlier fitted output:
    # preserve its explicit later allocation rather than choosing the entrance.
    wire['components'][0]['lifecycle'].update(createBefore='scope_start', disposeAfter='scope_end')
    wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    meta = entrance.decode(wire)
    _, _, invoke, run = setup([meta, *explicit_initializers()])
    saved = run()
    assert saved['status'] == 'ready' and errors(saved['value'], {'E1': 'owned'}, version=7) == []
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls
    rows = claims(); rows[-1].pop('executionSpec')
    result, binding = bind({'claims': rows}, saved)
    assert result['claims'][-1]['executionSpec']['phases'] == meta['phases']
    assert not binding['scientificApproval'] and not saved['scientificApproval']


def test_initializer_needing_prior_fit_cannot_be_moved_to_scope_start():
    from services.deep_research.contracts import DeepResearchError
    from test_deep_research_workflow_lifecycle_units import setup
    from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
    wire = authored()
    wire['components'][1]['lifecycle'].update(createBefore='scope_start', disposeAfter='scope_end')
    _, _, _, run = setup([entrance.decode(wire), *explicit_initializers()])
    with pytest.raises(DeepResearchError) as failed:
        run()
    assert failed.value.code == 'invalid_workflow_unit_response'
