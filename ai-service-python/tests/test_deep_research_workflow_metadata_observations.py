"""Raw group records and cross-group analysis have distinct existing roles."""
from copy import deepcopy
import pytest

from services.deep_research.workflow_metadata_ordered import (
    decode, descriptor, field_feedback, generation_prompt)
from services.deep_research.workflow_units import unit_errors, META
from services.deep_research.execution_workflow_blueprint import bind
from test_deep_research_workflow_metadata_ordered import authored
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_lifecycle_units import fixtures
from test_deep_research_workflow5_contract import claims
from test_deep_research_execution_spec import valid_analysis_spec
from services.deep_research.execution_spec import execution_spec_errors


def record_phase(wire):
    return next(p for p in wire['phases'] if p['kind'] == 'record' and p['groups'] == ['0'])


def test_native_observation_schema_prevents_shared_cross_group_raw_record():
    old = descriptor(); new = descriptor(2)
    assert new['name'] == 'ordered_workflow_observations_v2'
    branches = new['schema']['$defs']['phase']['anyOf']
    other, record = branches
    assert other['properties']['kind']['enum'] == ['fit', 'setup', 'evaluate']
    assert record['properties']['kind'] == {'const': 'record'}
    assert record['properties']['groups']['maxItems'] == 1
    assert record['properties']['sharing'] == {'const': 'per_group'}
    assert record['properties']['groups']['items']['pattern'] == '^[01]+$'
    assert new['schema']['properties']['components']['items']['properties']['appliesTo']['items']['pattern'] == '^[01]+$'
    assert descriptor() == old


@pytest.mark.parametrize('groups,sharing', [(['0', '1'], 'shared'),
    (['0', '1'], 'per_group'), (['0'], 'shared'), ([], 'per_group')])
def test_bad_record_preserves_choices_and_requests_model_revision(groups, sharing):
    wire = authored(); p = record_phase(wire); p.update(groups=groups, sharing=sharing)
    before = deepcopy(wire)
    with pytest.raises(ValueError): decode(wire, 2)
    feedback = field_feedback(wire, {'E1': 'owned'}, 2)
    issue = next(x for x in feedback['issues'] if x['code'] == 'ordered.record_scope')
    assert issue['actualGroups'] == groups and issue['actualSharing'] == sharing
    assert wire == before and not feedback['scientificApproval']


@pytest.mark.parametrize('group', ['arm_skip', 'G1', '', None, True])
def test_group_identifiers_cannot_silently_diverge_from_public_factor_and_budget_interface(group):
    wire = authored(); wire['components'][0]['appliesTo'] = [group]
    before = deepcopy(wire)
    with pytest.raises(ValueError): decode(wire, 2)
    issue = next(x for x in field_feedback(wire, {'E1': 'owned'}, 2)['issues'] if x['code'] == 'ordered.group_id')
    assert issue['actual'] == group and wire == before


@pytest.mark.parametrize('change,code', [('width', 'ordered.group_width'), ('coverage', 'ordered.group_coverage')])
def test_missing_factor_combinations_or_mixed_widths_are_not_mapped_or_filled(change, code):
    wire = authored()
    for root, key in [('components', 'appliesTo'), ('phases', 'groups')]:
        for row in wire[root]:
            row[key] = [('00' if g == '0' else '11') if change == 'coverage' or root == 'components' else g for g in row[key]]
    before = deepcopy(wire)
    with pytest.raises(ValueError): decode(wire, 2)
    assert code in [x['code'] for x in field_feedback(wire, {'E1': 'owned'}, 2)['issues']]
    assert wire == before


def test_observation_contract_still_rejects_control_reading_treatment_output():
    wire = authored(); p = record_phase(wire)
    p['reads'].append({'phaseId': 'eval1', 'outputId': 'metrics', 'selector': 'treatment metrics'})
    assert 'timeline.input.group_leak' in unit_errors(decode(wire, 2), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)


def test_one_revision_preserves_separate_records_and_complete_analysis_claim():
    wire = authored(); bad = deepcopy(wire); record_phase(bad).update(groups=['0', '1'], sharing='shared')
    r, _, invoke, run = setup_repair([response(bad), response(wire), *map(response, fixtures()[2])])
    r['workflowMetadataRepairContractVersion'] = 12
    saved = run()
    assert saved['units']['metadata']['value'] is None
    assert saved['units']['metadata']['response'] == response(bad)
    assert saved['metadataRepair']['value'] == decode(wire, 2) and not saved['scientificApproval']
    assert saved['units']['metadata']['request']['extra']['response_format']['name'] == 'ordered_workflow_observations_v2'
    # The lifecycle fixture deliberately covers only workflow-linked roles;
    # add the separate, structurally complete analysis rather than omitting it.
    analysis = {'claimId': 'paired_analysis', 'kind': 'proposal', 'designRole': 'analysis',
        'designContractVersion': 2, 'text': 'Proposed paired analysis, not measured results.',
        'executionSpec': valid_analysis_spec(), 'evidenceRefs': []}
    assert execution_spec_errors('analysis', analysis['executionSpec']) == []
    rows = claims(); rows.insert(-1, deepcopy(analysis))
    rows[-1].pop('executionSpec')
    result, receipt = bind({'claims': rows}, saved)
    assert next(c for c in result['claims'] if c['designRole'] == 'analysis') == analysis
    assert analysis['executionSpec']['effects'] and not receipt['scientificApproval']
    count = invoke.call_count
    assert run() == saved and invoke.call_count == count


def test_existing_ordered_prompt_is_frozen_and_analysis_remains_mandatory_in_new_role():
    old = generation_prompt('{}', {})
    new = generation_prompt('{}', {}, 2)
    assert 'Observation interface:' not in old and 'Observation interface:' in new
    assert 'later mandatory analysis' in new and generation_prompt('{}', {}) == old
