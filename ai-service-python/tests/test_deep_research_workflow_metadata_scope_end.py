from copy import deepcopy
import pytest

from services.deep_research import workflow_metadata_scope_end as scoped
from services.deep_research import workflow_metadata_single_group as scalar
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps import primitives


@pytest.mark.parametrize('factory', [lambda: authored(), lambda: authored(primitives)])
def test_existing_exact_boundaries_are_unchanged(factory):
    wire = factory(); before = deepcopy(wire)
    assert scoped.expanded(wire) == (wire, [])
    assert scoped.decode(wire) == scalar.decode(wire) and wire == before


def test_explicit_frame_end_keeps_state_through_all_declared_observations():
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    before = deepcopy(wire); expanded, bounds = scoped.expanded(wire)
    assert expanded['components'][1]['lifecycle']['disposeAfter'] == len(wire['steps'])-1
    assert bounds[0]['componentIndex'] == 1 and bounds[0]['scope'] == 'per_frame'
    assert unit_errors(scoped.decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    assert wire == before


def test_scope_end_never_changes_allocation_scope_or_operations():
    wire = authored()
    for c in wire['components']: c['lifecycle']['disposeAfter'] = 'scope_end'
    old = deepcopy(wire); out, _ = scoped.expanded(wire)
    assert out['steps'] == old['steps']
    for a, b in zip(out['components'], old['components']):
        assert a['appliesTo'] == b['appliesTo']
        assert a['lifecycle']['scope'] == b['lifecycle']['scope']
        assert a['lifecycle']['createBefore'] == b['lifecycle']['createBefore']
        if b['lifecycle']['scope'] == 'per_repeat': assert a['lifecycle']['disposeAfter'] is None


def test_explicit_early_release_is_still_rejected_not_silently_extended():
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 1
    assert any(x['code'] == 'timeline.input.after_disposal'
               for x in scoped.field_feedback(wire, {'E1': 'owned'})['issues'])
    assert scoped.expanded(wire)[0] == wire


def test_no_frame_block_or_unknown_scope_cannot_be_invented():
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    for step in wire['steps']: step['scope'] = 'per_repeat'
    with pytest.raises(ValueError): scoped.decode(wire)
    wire['components'][1]['lifecycle']['scope'] = 'invented'
    with pytest.raises(ValueError): scoped.decode(wire)


def test_scope_end_does_not_allow_cross_arm_access_or_escape_frame_scope():
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    wire['steps'][2]['reads'].append({'state': 'added', 'selector': 'treatment only'})
    assert any(x['code'] == 'timeline.input.group_leak'
               for x in scoped.field_feedback(wire, {'E1': 'owned'})['issues'])
    wire['steps'][2]['scope'] = 'per_repeat'
    assert unit_errors(scoped.decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)


def test_schema_operator_is_explicit_and_old_schema_is_unmodified():
    before = scalar.descriptor(); current = scoped.descriptor()
    branches = current['schema']['$defs']['lifecycle']['properties']['disposeAfter']['anyOf']
    assert {'const': 'scope_end'} in branches and scalar.descriptor() == before
    assert 'scope_end' not in str(before) and current['name'] == scoped.NAME


def test_explicit_scope_end_uses_original_full_assembly_and_public_binding():
    from test_deep_research_workflow_lifecycle_units import setup
    from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
    from test_deep_research_workflow5_contract import claims
    from services.deep_research.execution_workflow_blueprint import errors, bind
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    meta = scoped.decode(wire)
    _, _, invoke, run = setup([meta, *explicit_initializers()])
    saved = run()
    assert saved['status'] == 'ready' and errors(saved['value'], {'E1': 'owned'}, version=7) == []
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls
    rows = claims(); rows[-1].pop('executionSpec')
    result, binding = bind({'claims': rows}, saved)
    assert result['claims'][-1]['executionSpec']['phases'] == meta['phases']
    assert not binding['scientificApproval'] and not saved['scientificApproval']
