"""Representation assessment only: no runtime activation or scientific credit."""
from copy import deepcopy
import pytest

from services.deep_research.workflow_metadata_ordered import decode, descriptor, complete_scaffolding
from services.deep_research.workflow_units import unit_errors, META, descriptor as canonical_descriptor
from services.deep_research.workflow_lifecycle_units import timeline_spec
from services.deep_research.workflow_lifecycle import lifecycle_issues, _creation_point
from test_deep_research_workflow_lifecycle_units import fixtures


def authored():
    """A new engineering fixture, never a historical-output migration."""
    meta = deepcopy(fixtures()[1])
    ids = [p['phaseId'] for p in meta['phases']]
    first_frame = next((i for i, p in enumerate(meta['phases']) if p['scope'] == 'per_frame'), 0)
    for c in meta['components']:
        life = c['lifecycle']; after = life.pop('createAfter')
        before = max((ids.index(pid) for pid in after), default=-1) + 1
        if not after and life['scope'] == 'per_frame': before = first_frame
        life['createBefore'] = ids[before]
    for p in meta['phases']: del p['after']
    return meta


def test_explicit_boundaries_lower_without_reordering_or_changing_scientific_values():
    wire = authored(); before = deepcopy(wire); old = fixtures()[1]; meta = decode(wire)
    assert wire == before and complete_scaffolding(wire)
    assert unit_errors(meta, {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    for actual, original in zip(meta['phases'], old['phases']):
        assert {k: v for k, v in actual.items() if k != 'after'} == {
            k: v for k, v in original.items() if k != 'after'}
    for key in old.keys() - {'phases', 'components'}: assert meta[key] == old[key]
    phase_map = {p['phaseId']: (i, p) for i, p in enumerate(meta['phases'])}
    start = next(i for i, p in enumerate(meta['phases']) if p['scope'] == 'per_frame')
    for new, original in zip(meta['components'], old['components']):
        assert new['componentId'] == original['componentId']
        assert new['appliesTo'] == original['appliesTo']
        assert new['lifecycle']['scope'] == original['lifecycle']['scope']
        assert new['lifecycle']['disposeAfter'] == original['lifecycle']['disposeAfter']
        assert _creation_point(new['lifecycle'], phase_map, start) == _creation_point(
            original['lifecycle'], phase_map, start)
    assert lifecycle_issues(timeline_spec(meta)) == lifecycle_issues(timeline_spec(old))


@pytest.mark.parametrize('change', ['old_wire', 'missing', 'extra', 'duplicate_phase',
    'unknown_boundary', 'array_boundary', 'missing_phase_field', 'extra_lifecycle', 'nonfinite'])
def test_unknown_or_ambiguous_wire_is_not_fixed_or_reinterpreted(change):
    wire = authored()
    if change == 'old_wire': wire = fixtures()[1]
    elif change == 'missing': del wire['components']
    elif change == 'extra': wire['unknown'] = 'must not disappear'
    elif change == 'duplicate_phase': wire['phases'][1]['phaseId'] = wire['phases'][0]['phaseId']
    elif change == 'unknown_boundary': wire['components'][0]['lifecycle']['createBefore'] = 'missing'
    elif change == 'array_boundary': wire['components'][0]['lifecycle']['createBefore'] = []
    elif change == 'missing_phase_field': del wire['phases'][0]['reads']
    elif change == 'extra_lifecycle': wire['components'][0]['lifecycle']['createAfter'] = []
    else: wire['phases'][0]['budget']['perExecution'] = float('nan')
    with pytest.raises(ValueError): decode(wire)


@pytest.mark.parametrize('change,code', [('late_creation', 'timeline.input.before_creation'),
    ('group_leak', 'timeline.input.group_leak'), ('bad_budget', 'timeline.phase.budget'),
    ('future_read', 'timeline.input.future_output'), ('early_disposal', 'timeline.cycle')])
def test_semantically_wrong_authored_plans_still_fail_original_checks(change, code):
    wire = authored()
    if change == 'late_creation': wire['components'][0]['lifecycle']['createBefore'] = wire['phases'][-1]['phaseId']
    elif change == 'group_leak': wire['components'][0]['appliesTo'] = ['some_other_group']
    elif change == 'bad_budget': wire['phases'][0]['budget'] = None
    elif change == 'future_read': wire['phases'][0]['reads'].append({
        'phaseId': wire['phases'][-1]['phaseId'], 'outputId': wire['phases'][-1]['outputs'][0], 'selector': 'chosen'})
    else: wire['components'][0]['lifecycle']['disposeAfter'] = wire['phases'][0]['phaseId']
    before = deepcopy(wire)
    errors = unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    assert code in errors
    assert wire == before


def test_schema_uses_one_order_and_explicit_before_boundary_only():
    schema = descriptor(); old = canonical_descriptor(META, 7)
    assert schema['name'] != old['name']
    defs = schema['schema']['$defs']
    assert 'after' not in defs['phase']['properties']
    assert 'createBefore' in defs['lifecycle']['required']
    assert 'createAfter' not in defs['lifecycle']['properties']
    assert 'after' in old['schema']['$defs']['phase']['properties']


def test_lowered_metadata_uses_unchanged_full_assembly_and_public_binding():
    from test_deep_research_workflow_lifecycle_units import setup
    from test_deep_research_workflow5_contract import claims
    from services.deep_research.execution_workflow_blueprint import errors, bind
    meta = decode(authored()); _, _, inits = fixtures()
    record, _, invoke, run = setup([meta, *inits])
    saved = run()
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    assert errors(saved['value'], {'E1': 'owned'}, version=7) == []
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls
    rows = claims(); rows[-1].pop('executionSpec')
    report, binding = bind({'claims': rows}, saved)
    assert report['claims'][-1]['executionSpec']['phases'] == meta['phases']
    assert not binding['scientificApproval']


def test_every_supported_boundary_matches_authored_position_in_original_event_model():
    for prefix in range(3):
        for frames in range(1, 4):
            for scope in ('per_repeat', 'per_frame'):
                for boundary in range(prefix + frames):
                    wire = authored(); phase = wire['phases'][0]
                    wire['phases'] = [{**deepcopy(phase), 'phaseId': f'p{i}',
                        'scope': 'per_repeat' if i < prefix else 'per_frame'} for i in range(prefix + frames)]
                    wire['components'] = [{**wire['components'][0], 'lifecycle': {
                        'scope': scope, 'createBefore': f'p{boundary}', 'disposeAfter': None}}]
                    if scope == 'per_frame' and boundary < prefix:
                        with pytest.raises(ValueError): decode(wire)
                        continue
                    lowered = decode(wire)
                    positions = {p['phaseId']: (i, p) for i, p in enumerate(lowered['phases'])}
                    assert _creation_point(lowered['components'][0]['lifecycle'], positions, prefix) == boundary - 0.5
