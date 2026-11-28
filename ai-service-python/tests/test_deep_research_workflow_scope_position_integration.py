from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_scope_position as local
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import descriptor_for, options_for_record
from test_deep_research_workflow_scope_position import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def test_complete_bad_coordinate_gets_one_revision_then_original_assembly_and_resume():
    wire = wire_value(); bad = deepcopy(wire)
    bad['components'][1]['lifecycle'][local.FIELD] = 99
    record, original, invoke, run = setup_repair([
        response(bad), response(wire), *map(response, explicit_initializers())])
    record.update(workflowMetadataRepairContractVersion=19, workflowInitializationOutputContractVersion=1)
    saved = run(); revision = saved['metadataRepair']
    assert saved['status'] == 'ready' and revision['value'] == local.decode(wire)
    assert saved['units']['metadata']['response'] == response(bad)
    data = input_value(revision['request']['prompt'])
    assert data['invalidMetadata'] == bad
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    issue = data['fieldFeedback']['issues'][0]
    assert issue['actual'] == 99 and issue['path'].endswith('/'+local.FIELD)
    assert revision['request']['extra']['response_format'] == local.descriptor()
    assert run() == saved and invoke.call_count == 5 and not saved['scientificApproval']


def test_same_invalid_reply_fails_once_and_is_retained_on_resume():
    bad = wire_value(); bad['components'][1]['lifecycle'][local.FIELD] = -1
    record, _, invoke, run = setup_repair([response(bad), response(bad)])
    record['workflowMetadataRepairContractVersion'] = 19
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    assert record['state']['executionWorkflowBlueprint']['metadataRepair']['response'] == response(bad)


def test_allocation_cannot_make_a_later_initializer_dependency_available():
    wire = wire_value(); wire['components'][1]['lifecycle'][local.FIELD] = 0
    record, _, invoke, run = setup_repair([response(wire), *map(response, explicit_initializers())])
    record['workflowMetadataRepairContractVersion'] = 19
    with pytest.raises(DeepResearchError) as failed: run()
    assert failed.value.code == 'invalid_workflow_unit_response'
    assert 'metadataRepair' not in record['state']['executionWorkflowBlueprint']
    assert invoke.call_count == 4


def test_transport_uses_distinct_new_schema_with_original_role_and_output_budget():
    record, _, _, _ = setup_repair([])
    record['workflowMetadataRepairContractVersion'] = 18
    legacy = descriptor_for(record, 'plan_workflow_meta')
    record['workflowMetadataRepairContractVersion'] = 19
    for node in ('plan_workflow_meta', 'repair_workflow_meta'):
        options = options_for_record(record, node, {'temperature':0.0})
        assert options['response_format'] == local.descriptor()
        assert options['max_tokens'] == 3072 and options['reasoning_effort'] == 'none'
    record['workflowMetadataRepairContractVersion'] = 18
    assert descriptor_for(record, 'plan_workflow_meta') == legacy


def test_prompt_round_trip_does_not_omit_sources_or_invalid_coordinates():
    wire = wire_value(); feedback = {'issues':[{'actual':99}]}
    data = {'question':'Original question', 'sources':[{'quote':'Full original quote', 'id':'E1'}]}
    prompt = local.revision_prompt(json.dumps(data), wire, feedback)
    assert input_value(prompt) == {'authoritativeInput':data, 'invalidMetadata':wire, 'fieldFeedback':feedback}
    assert 'among frame steps for per_frame' in prompt and 'Other indices global' in prompt
