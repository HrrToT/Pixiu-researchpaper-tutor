from copy import deepcopy
import json
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_metadata_rows import encode
from services.deep_research.workflow_metadata_revision5 import field_feedback, over_capacity
from test_deep_research_workflow_metadata_repair import setup_repair, response, invalid_metadata
from test_deep_research_workflow_lifecycle_units import fixtures


def padded_response(value, padding=9000):
    result = response(encode(value))
    result['rawContent'] = result['content'] + ' '*padding
    return result


def test_formatting_only_capacity_is_versioned_and_raw_response_is_retained():
    _, meta, inits = fixtures()
    for version in (4, 5):
        original = padded_response(invalid_metadata()); revision = padded_response(meta)
        before = deepcopy(original)
        r, _, invoke, run = setup_repair([original, revision, *map(response, inits)])
        r['workflowMetadataRepairContractVersion'] = version
        if version == 4:
            with pytest.raises(DeepResearchError): run()
            assert invoke.call_count == 1
        else:
            result = run(); assert result['metadataRepair']['status'] == 'ready'
            assert result['units']['metadata']['response'] == before
            assert result['metadataRepair']['response'] == revision
            calls = invoke.call_count; assert run() == result and invoke.call_count == calls
            assert not result['scientificApproval']


@pytest.mark.parametrize('kind', ['raw', 'content', 'truncated'])
def test_raw_content_and_truncation_caps_remain_independent_and_cannot_trigger_repair(kind):
    meta = invalid_metadata()
    if kind == 'content': meta['unresolved'] = ['x'*9000]
    bad = padded_response(meta, 17000 if kind == 'raw' else 0)
    if kind == 'truncated': bad['finishReason'] = 'length'
    r, _, invoke, run = setup_repair([bad]); r['workflowMetadataRepairContractVersion'] = 5
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    saved = r['state']['executionWorkflowBlueprint']
    assert 'metadataRepair' not in saved and invoke.call_count == 1
    expected = 'unit.output_truncated' if kind == 'truncated' else 'unit.output_capacity'
    assert expected in saved['units']['metadata']['errors']


def test_reserved_component_feedback_does_not_delete_or_rename_original():
    wire = encode(fixtures()[1]); wire['componentRows'].append(['baseline', ['g'], ['per_repeat', [], None]])
    before = deepcopy(wire); feedback = field_feedback(wire)
    issue = next(x for x in feedback['issues'] if x['code'] == 'wire.component.reserved_name')
    assert issue['path'] == f'/componentRows/{len(wire["componentRows"])-1}/0'
    assert issue['actual'] == 'baseline' and wire == before
    assert not feedback['scientificApproval']


def test_removing_formatting_never_removes_semantic_errors():
    wire = encode(fixtures()[1]); wire['componentRows'][0][0] = 'baseline'
    assert not over_capacity(json.dumps(wire, indent=4), wire)
    assert any(x['code'] == 'wire.component.reserved_name' for x in field_feedback(wire)['issues'])
