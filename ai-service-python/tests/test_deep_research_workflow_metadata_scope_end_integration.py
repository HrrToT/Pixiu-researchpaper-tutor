from copy import deepcopy
import json
import pytest

from services.deep_research.workflow_metadata_scope_end import NAME, decode
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def scope_authored():
    wire = authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 'scope_end'
    return wire


def test_generation_revision_initialization_and_resume_use_explicit_scope_choice():
    wire = scope_authored(); bad = deepcopy(wire); bad['components'][0]['lifecycle']['createBefore'] = 'unknown'
    r, original, invoke, run = setup_repair([response(bad), response(wire), *map(response, explicit_initializers())])
    r['workflowMetadataRepairContractVersion'] = 15
    saved = run(); revision = saved['metadataRepair']
    assert saved['status'] == 'ready' and revision['value'] == decode(wire)
    assert saved['units']['metadata']['request']['extra']['response_format']['name'] == NAME
    assert not saved['scientificApproval'] and invoke.call_count == 5
    payload = input_value(revision['request']['prompt'])
    assert payload['invalidMetadata'] == bad
    assert payload['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert payload['fieldFeedback']['explicitScopeEndReleases'][0]['disposeAfter'] == 3
    before = deepcopy(saved); assert run() == before and invoke.call_count == 5
    assert revision['response'] == response(wire)


def test_received_exact_early_release_cannot_be_replaced_with_scope_end_implicitly():
    wire = scope_authored(); wire['components'][1]['lifecycle']['disposeAfter'] = 1
    r, _, invoke, run = setup_repair([response(wire), response(wire)])
    r['workflowMetadataRepairContractVersion'] = 15
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    saved = r['state']['executionWorkflowBlueprint']
    assert saved['metadataRepair']['response'] == response(wire)
    assert 'timeline.input.after_disposal' in saved['metadataRepair']['errors']
