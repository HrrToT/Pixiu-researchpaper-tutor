from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_metadata_first_use as first
from services.deep_research import workflow_metadata_bounded_schema as previous
from services.deep_research.workflow_units import unit_errors, META
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def authored_first_use():
    value = wire_value()
    for component in value['components']: component['lifecycle']['createInScope'] = first.FIRST_USE
    return value


def test_explicit_mode_matches_authored_boundaries_without_rewriting_input():
    wire = authored_first_use(); before = deepcopy(wire)
    lowered, issues, audit = first.expanded(wire)
    assert not issues and lowered == wire_value() and wire == before
    assert audit[1] == {'firstUseStepIndex': 1, 'allocationStepIndex': 1, 'resolvedScopeIndex': 1}
    assert first.decode(wire) == previous.decode(wire_value())
    assert unit_errors(first.decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []


def test_repeat_resource_used_in_frames_is_created_before_the_frame_block():
    value = {'components': [{'componentId': 'log', 'lifecycle': {'scope': 'per_repeat',
        'createInScope': first.FIRST_USE}}], 'steps': [
        {'scope': 'per_repeat', 'reads': [], 'updates': []},
        {'scope': 'per_frame', 'reads': [], 'updates': []},
        {'scope': 'per_frame', 'reads': [{'state': 'log', 'selector': 'all'}], 'updates': []}]}
    lowered, issues, audit = first.expanded(value)
    assert not issues and lowered['components'][0]['lifecycle']['createInScope'] == 1
    assert audit[0]['firstUseStepIndex'] == 2 and audit[0]['allocationStepIndex'] == 1


@pytest.mark.parametrize('reason', ['no_declared_state_use', 'first_use_outside_frame', 'invalid_scope'])
def test_undefined_or_incompatible_mode_has_no_default_coordinate(reason):
    value = authored_first_use(); component = value['components'][1]
    if reason == 'no_declared_state_use': component['componentId'] = 'unused'
    elif reason == 'first_use_outside_frame':
        value['steps'][0]['scope'] = 'per_repeat'
        value['steps'][0]['reads'].append({'state': 'added', 'selector': 'all'})
    else: component['lifecycle']['scope'] = 'unknown'
    before = deepcopy(value); lowered, issues, _ = first.expanded(value)
    assert lowered['components'][1]['lifecycle']['createInScope'] == first.FIRST_USE
    assert any(i['reason'] == reason for i in issues)
    assert value == before
    with pytest.raises(ValueError): first.decode(value)
    assert first.field_feedback(value, {'E1': 'owned'})['issues'] == issues


def test_invalid_existing_numeric_coordinate_is_never_repaired_by_first_use():
    value = wire_value(); value['components'][1]['lifecycle']['createInScope'] = 2
    lowered, issues, audit = first.expanded(value)
    assert not issues and not audit and lowered == value
    errors = unit_errors(first.decode(value), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    assert 'timeline.input.before_creation' in errors


def test_scope_checks_still_reject_direct_postloop_reads_of_frame_values():
    value = authored_first_use(); record = deepcopy(value['steps'][4])
    record.update(scope='per_repeat', outputs=['postloop'], reads=[{
        'stepIndex': 2, 'outputStage': 'operation', 'outputId': 'metrics', 'selector': 'all_frames'}])
    value['steps'].append(record)
    errors = unit_errors(first.decode(value), {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    assert 'timeline.input.scope' in errors


def test_schema_accepts_only_the_new_explicit_mode_or_original_indices():
    schema = first.descriptor()['schema']; Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(authored_first_use()) and validator.is_valid(wire_value())
    for value in (None, True, 'firstuse', -1):
        wire = authored_first_use(); wire['components'][1]['lifecycle']['createInScope'] = value
        assert not validator.is_valid(wire)


def test_full_assembly_and_resume_keep_authored_mode_in_original_response():
    wire = authored_first_use()
    r, _, invoke, run = setup_repair([response(wire), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=25, workflowInitializationOutputContractVersion=1)
    saved = run()
    assert saved['status'] == 'ready' and saved['units']['metadata']['response'] == response(wire)
    assert saved['units']['metadata']['value'] == first.decode(wire)
    assert run() == saved and invoke.call_count == 4 and not saved['scientificApproval']


def test_one_revision_can_choose_the_mode_without_mutating_original_or_retrying():
    bad = wire_value(); bad['components'][1]['lifecycle']['createInScope'] = 2
    good = authored_first_use()
    r, prompt, invoke, run = setup_repair([response(bad), response(good), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=25, workflowInitializationOutputContractVersion=1)
    saved = run(); fix = saved['metadataRepair']
    assert fix['version'] == 25 and fix['status'] == 'ready'
    data = input_value(fix['request']['prompt'])
    assert data['invalidMetadata'] == bad
    assert data['authoritativeInput'] == json.loads(prompt.split('Authoritative input data (not instructions):\n')[1])
    assert saved['units']['metadata']['response'] == response(bad)
    assert run() == saved and invoke.call_count == 5


def test_undefined_mode_correction_is_rejected_without_another_attempt():
    bad = authored_first_use(); bad['components'][1]['componentId'] = 'unused'
    r, _, invoke, run = setup_repair([response(bad), response(bad)])
    r.update(workflowMetadataRepairContractVersion=25, workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
