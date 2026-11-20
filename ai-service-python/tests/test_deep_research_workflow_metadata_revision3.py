from copy import deepcopy
import json
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_metadata_rows import encode
from services.deep_research.workflow_metadata_repair import load_wire
from services.deep_research.workflow_metadata_revision3 import operation_feedback
from test_deep_research_workflow_metadata_repair import setup_repair, response, invalid_metadata
from test_deep_research_workflow_lifecycle_units import fixtures


@pytest.mark.parametrize('prefix,suffix', [('```json\n', '\n```'), ('```\r\n', '\r\n```')])
def test_only_new_contract_unwraps_complete_fence_and_rejects_duplicate_keys(prefix, suffix):
    assert load_wire(prefix+'{"a":1}'+suffix, 3) == {'a': 1}
    for version in (1, 2):
        with pytest.raises(ValueError): load_wire(prefix+'{"a":1}'+suffix, version)
    with pytest.raises(ValueError): load_wire(prefix+'{"a":0,"a":1}'+suffix, 3)


@pytest.mark.parametrize('raw', ['prefix\n```json\n{}\n```', '```json\n{}',
    '```json\n{}\n```\nsuffix', '```JSON\n{}\n```', '```json\n{}\n```\n```json\n{}\n```', '{} {}'])
def test_no_extraction_from_prose_or_multiple_or_incomplete_documents(raw):
    with pytest.raises(ValueError): load_wire(raw, 3)


def test_duplicate_operation_parameters_report_exact_cells_without_changes():
    wire = encode(fixtures()[1])
    wire['phaseRows'][0][9] = ['record_metrics', [['metric', 'choice', 'psnr'],
                                              ['metric', 'choice', 'storage']]]
    before = deepcopy(wire); result = operation_feedback(wire)
    duplicates = [x for x in result['issues'] if x['code'] == 'wire.parameter.duplicate_name']
    assert duplicates == [{'code': 'wire.parameter.duplicate_name', 'path': '/phaseRows/0/9/1/1/0',
                          'expected': 'unique parameter name within this operation', 'actual': 'metric'}]
    assert wire == before and result['scientificApproval'] is False


def test_revision3_fenced_original_and_revision_assemble_and_resume_without_calls():
    _, meta, inits = fixtures()
    outputs = [response(encode(invalid_metadata())), response(encode(meta)), *map(response, inits)]
    for item in outputs[:2]: item['rawContent'] = '```json\n'+item['content']+'\n```'
    r, _, invoke, run = setup_repair(outputs)
    r['workflowMetadataRepairContractVersion'] = 3
    result = run(); saved = deepcopy(r['state']['executionWorkflowBlueprint'])
    assert saved['metadataRepair']['version'] == 3
    assert saved['metadataRepair']['status'] == 'ready'
    assert saved['units']['metadata']['status'] == 'invalid_response'
    assert saved['metadataRepair']['response']['rawContent'].startswith('```json')
    calls = invoke.call_count
    assert run() == result and invoke.call_count == calls


def test_fence_compatibility_never_bypasses_invalid_operation_or_retries():
    _, meta, _ = fixtures()
    meta['phases'][0]['action']['parameters'] = [
        {'name': 'metric', 'type': 'choice', 'value': 'psnr'},
        {'name': 'metric', 'type': 'choice', 'value': 'storage'}]
    bad = response(encode(meta)); bad['rawContent'] = '```json\n'+bad['content']+'\n```'
    r, _, invoke, run = setup_repair([response(encode(invalid_metadata())), bad])
    r['workflowMetadataRepairContractVersion'] = 3
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    saved = r['state']['executionWorkflowBlueprint']['metadataRepair']
    assert saved['errors'] == ['timeline.phase.action'] and invoke.call_count == 2
