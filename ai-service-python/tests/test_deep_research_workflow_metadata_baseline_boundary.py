from copy import deepcopy

import pytest

from services.deep_research import workflow_metadata_baseline_boundary as boundary
from services.deep_research.structured_output import messages_for_record, ARRAY_NODES
from services.deep_research.experiment_planning import request_identity
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import descriptor_for
from services.deep_research.workflow_metadata_first_use import descriptor
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_first_use import authored_first_use


def record():
    r, _, _, _ = setup_repair([])
    r.update(workflowMetadataRepairContractVersion=26, workflowInitializationOutputContractVersion=1)
    return r


def test_only_private_metadata_nodes_receive_owner_boundary_within_original_reservation():
    r = record(); prompt = 'Original source bytes: 基线训练不是已经发布的检查点。\n'
    assert len(boundary.SYSTEM_POLICY.encode()) + 128 <= 1024
    for node in boundary.NODES:
        request = request_identity(r, node, prompt, {'temperature': 0.0})
        assert request['messages'] == boundary.messages(prompt)
        assert request['extra']['response_format'] == descriptor()
        assert request['extra']['max_tokens'] == 3072 and request['extra']['reasoning_effort'] == 'none'
    assert 'budget.baseline' in boundary.SYSTEM_POLICY and 'budget.recovery' in boundary.SYSTEM_POLICY
    assert 'Never clear a real training budget' in boundary.SYSTEM_POLICY
    assert 'baselineInitialization owns the pre-fit state' in boundary.SYSTEM_POLICY


def test_public_review_initializer_and_other_roles_remain_byte_identical():
    new = record(); old = deepcopy(new); old['workflowMetadataRepairContractVersion'] = 25
    nodes = ARRAY_NODES | {'synthesize', 'synthesize_compact', 'synthesize_audience',
        'plan_experiment', 'plan_workflow_init', 'plan_scientific_outline'}
    for node in nodes:
        assert messages_for_record(new, node, 'unchanged') == messages_for_record(old, node, 'unchanged'), node
    for node in boundary.NODES:
        assert messages_for_record(new, node, 'unchanged') != messages_for_record(old, node, 'unchanged')
        assert descriptor_for(new, node) == descriptor_for(old, node)


@pytest.mark.parametrize('marker', [None, True, '26', 26.0, 25])
def test_missing_legacy_or_mistyped_marker_cannot_change_metadata_messages(marker):
    r = record(); r['workflowMetadataRepairContractVersion'] = marker
    assert not boundary.enabled(r, 'plan_workflow_meta')
    assert messages_for_record(r, 'plan_workflow_meta', 'source')[0]['content'] != boundary.SYSTEM_POLICY


def test_complete_assembly_and_resume_preserve_input_and_native_choices():
    wire = authored_first_use()
    r, _, invoke, run = setup_repair([response(wire), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=26, workflowInitializationOutputContractVersion=1)
    saved = run(); unit = saved['units']['metadata']
    assert saved['status'] == 'ready' and unit['response'] == response(wire)
    assert unit['request']['messages'][0]['content'] == boundary.SYSTEM_POLICY
    assert run() == saved and invoke.call_count == 4


def test_setup_with_training_budget_is_not_automatically_relabelled_or_zeroed():
    bad = authored_first_use(); bad['steps'][0]['kind'] = 'setup'
    original_budget = deepcopy(bad['steps'][0]['budget'])
    assert original_budget is not None
    r, _, invoke, run = setup_repair([response(bad), response(bad)])
    r.update(workflowMetadataRepairContractVersion=26, workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    saved = r['state']['executionWorkflowBlueprint']
    assert 'timeline.phase.nonfit_budget' in saved['metadataRepair']['errors']
    assert saved['units']['metadata']['response'] == response(bad)
    assert bad['steps'][0]['budget'] == original_budget and invoke.call_count == 2
