from copy import deepcopy
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import dispatch_options, options_for_record
from services.deep_research.runtime import research_model_options
from services.deep_research.workflow_metadata_rows import encode
from test_deep_research_workflow_metadata_repair import setup_repair, response, invalid_metadata
from test_deep_research_workflow_lifecycle_units import fixtures


@pytest.mark.parametrize('version', [1, 2, 3, 4])
@pytest.mark.parametrize('node', ['plan_workflow_meta', 'repair_workflow_meta', 'plan_workflow_init'])
def test_output_cap_is_frozen_by_record_and_matches_request_fingerprint(version, node):
    record, _, _, _ = setup_repair(); record['workflowMetadataRepairContractVersion'] = version
    before = deepcopy(record)
    request = request_identity(record, node, 'complete proposal', {'temperature': 0.0})
    expected = 6144 if node == 'plan_workflow_init' else (3072 if version == 4 else 2048)
    assert request['extra']['max_tokens'] == expected
    dispatched = dispatch_options(record, node, request['extra'])
    rebuilt = options_for_record(record, node, research_model_options(node, dispatched))
    assert rebuilt == request['extra'] and record == before
    if version == 4 and node != 'plan_workflow_init':
        assert options_for_record(record, node, {**research_model_options(node, {}), 'max_tokens': 999999})['max_tokens'] == 3072


def test_v4_truncation_is_explicit_and_never_repaired_or_resent():
    bad = {'content': 'null', 'rawContent': '{"phaseRows":[', 'finishReason': 'length'}
    record, _, invoke, run = setup_repair([bad])
    record['workflowMetadataRepairContractVersion'] = 4
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    saved = record['state']['executionWorkflowBlueprint']
    assert saved['units']['metadata']['errors'] == ['unit.output_truncated']
    assert 'metadataRepair' not in saved and invoke.call_count == 1


def test_v4_does_not_accept_oversize_valid_json_or_spend_a_revision():
    bad = response(encode(invalid_metadata())); bad['rawContent'] = bad['content']+' '*8192
    record, _, invoke, run = setup_repair([bad]); record['workflowMetadataRepairContractVersion'] = 4
    with pytest.raises(DeepResearchError): run()
    saved = record['state']['executionWorkflowBlueprint']
    assert 'unit.output_capacity' in saved['units']['metadata']['errors']
    assert 'metadataRepair' not in saved and invoke.call_count == 1


def test_v4_fenced_revision_retains_graph_and_resumes_without_provider_calls():
    _, meta, inits = fixtures()
    revised = response(encode(meta)); revised['rawContent'] = '```json\n'+revised['content']+'\n```'
    record, _, invoke, run = setup_repair([response(encode(invalid_metadata())), revised, *map(response, inits)])
    record['workflowMetadataRepairContractVersion'] = 4
    result = run(); assert result['metadataRepair']['version'] == 4
    calls = invoke.call_count
    assert run() == result and invoke.call_count == calls
    assert not result['scientificApproval']
