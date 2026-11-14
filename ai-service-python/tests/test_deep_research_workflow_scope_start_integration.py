from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_scope_start as entrance
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import descriptor_for, options_for_record
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def wire_value():
    wire = authored()
    wire['components'][0]['lifecycle'].update(createBefore='scope_start', disposeAfter='scope_end')
    wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    return wire


def test_new_generation_revision_assembly_and_resume_preserve_original_inputs():
    wire = wire_value(); bad = deepcopy(wire)
    bad['components'][1]['lifecycle']['createBefore'] = 'unknown'
    record, original, invoke, run = setup_repair([
        response(bad), response(wire), *map(response, explicit_initializers())])
    record.update(workflowMetadataRepairContractVersion=18, workflowInitializationOutputContractVersion=1)
    saved = run(); repair = saved['metadataRepair']
    assert saved['status'] == 'ready' and repair['value'] == entrance.decode(wire)
    assert saved['units']['metadata']['response'] == response(bad)
    data = input_value(repair['request']['prompt'])
    assert data['invalidMetadata'] == bad
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert repair['request']['extra']['response_format'] == entrance.descriptor()
    assert data['fieldFeedback']['explicitScopeStartAllocations'][0]['createBefore'] == 0
    before = deepcopy(saved)
    assert run() == before and invoke.call_count == 5
    assert not repair['scientificApproval'] and not saved['scientificApproval']


def test_unchanged_bad_allocation_still_fails_once_and_is_not_retried():
    bad = wire_value(); bad['components'][1]['lifecycle']['createBefore'] = 'unknown'
    record, _, invoke, run = setup_repair([response(bad), response(bad)])
    record['workflowMetadataRepairContractVersion'] = 18
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    assert record['state']['executionWorkflowBlueprint']['metadataRepair']['response'] == response(bad)


def test_legacy_descriptor_and_new_physical_options_remain_distinct():
    record, _, _, _ = setup_repair([])
    record['workflowMetadataRepairContractVersion'] = 17
    old = descriptor_for(record, 'plan_workflow_meta')
    record['workflowMetadataRepairContractVersion'] = 18
    for node in ('plan_workflow_meta', 'repair_workflow_meta'):
        assert descriptor_for(record, node) == entrance.descriptor()
        options = options_for_record(record, node, {'temperature': 0.0})
        assert options['max_tokens'] == 3072 and options['reasoning_effort'] == 'none'
        assert options['response_format'] == entrance.descriptor()
    record['workflowMetadataRepairContractVersion'] = 17
    assert descriptor_for(record, 'plan_workflow_meta') == old
    assert old['name'] == 'typed_scope_release_steps_v3'


def test_revision_prompt_keeps_every_input_value_and_complete_scope_rules():
    from services.deep_research.workflow_metadata_scope_end import COUNT_POLICY
    wire = wire_value(); before = deepcopy(wire)
    data = {'question': 'Original exact question', 'sources': [{'id': 'E1', 'quote': 'Entire original quote'}]}
    feedback = {'issues': [{'path': '/components/1/lifecycle/createBefore', 'actual': 0}]}
    prompt = entrance.revision_prompt(json.dumps(data), wire, feedback)
    assert input_value(prompt) == {'authoritativeInput': data, 'invalidMetadata': wire, 'fieldFeedback': feedback}
    assert wire == before and COUNT_POLICY in prompt
    assert 'scope_start at repeat/frame entrance' in prompt
    assert 'later index for dependent init' in prompt
    assert 'Release after ALL consumers' in prompt
