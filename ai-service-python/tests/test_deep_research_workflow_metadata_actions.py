from copy import deepcopy
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_metadata_actions import encode, decode, descriptor, field_feedback, NAME
from services.deep_research.workflow_metadata_repair import load_wire
from services.deep_research.workflow_units import META, unit_prompt, unit_errors, descriptor as unit_descriptor
from test_deep_research_workflow_lifecycle_units import fixtures
from test_deep_research_workflow_metadata_repair import setup_repair, response, invalid_metadata


def test_named_operation_grammar_is_lossless_and_native_schema_matches():
    meta = fixtures()[1]; before = deepcopy(meta); wire = encode(meta)
    assert all(isinstance(p[9], dict) for p in wire['phaseRows'])
    canonical = unit_descriptor(META, 7)['schema']['$defs']
    assert descriptor()['schema']['$defs']['operation'] == canonical['operation']
    assert descriptor()['schema']['$defs']['parameter'] == canonical['parameter']
    assert unit_errors(decode(wire), {'E1': 'owned'}, node=META, version=7, metadata_rows=True) == []
    assert decode(wire) == meta == before
    assert descriptor()['name'] == NAME
    assert not field_feedback(wire)['issues']


@pytest.mark.parametrize('action', [
    ['render', [['arm', 'choice', 'a']], ['count', []]],
    ['render', [['arm', 'choice', 'a']], 'count', []],
    [{'action': 'render', 'parameters': []}, {'action': 'count', 'parameters': []}],
    {'action': 'render', 'parameters': [], 'second': 'count'},
])
def test_ambiguous_multiple_operations_are_preserved_and_never_split_by_code(action):
    wire = encode(fixtures()[1]); wire['phaseRows'][0][9] = action; before = deepcopy(wire)
    with pytest.raises(ValueError): decode(wire)
    feedback = field_feedback(wire)
    assert any(x['path'] == '/phaseRows/0/9' for x in feedback['issues'])
    assert wire == before and not feedback['scientificApproval']


def test_new_prompt_has_no_competing_action_tuple_instructions():
    body = unit_prompt('{}', node=META, context={}, version=7, metadata_rows=True,
                       metadata_rows_contract=2, metadata_action_objects=True)
    assert NAME in body and 'ONE action OBJECT' in body
    assert 'Each action is [action,[[name,type,value],...]].' not in body
    assert 'workflow_metadata_rows_v1' not in body


def test_complete_invalid_action_gets_one_model_revision_then_full_initialization_and_resume():
    _, meta, inits = fixtures(); bad = encode(meta)
    bad['phaseRows'][0][9] = ['render', [], ['count', []]]
    revised = response(encode(meta))
    r, _, invoke, run = setup_repair([response(bad), revised, *map(response, inits)])
    r['workflowMetadataRepairContractVersion'] = 6
    result = run(); original = result['units']['metadata']
    assert original['value'] is None and original['errors'] == ['unit.json']
    assert original['response'] == response(bad)
    assert result['metadataRepair']['status'] == 'ready' and result['metadataRepair']['version'] == 6
    assert result['metadataRepair']['response'] == revised
    calls = invoke.call_count
    assert run() == result and invoke.call_count == calls
    assert result['scientificApproval'] is False


def test_still_invalid_revision_is_cached_without_second_attempt():
    bad = encode(invalid_metadata()); bad['phaseRows'][0][9] = ['a', [], ['b', []]]
    r, _, invoke, run = setup_repair([response(bad), response(bad)])
    r['workflowMetadataRepairContractVersion'] = 6
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    assert r['state']['executionWorkflowBlueprint']['metadataRepair']['errors'] == ['unit.json']


def test_duplicate_keys_in_named_operation_are_not_normalized_away():
    with pytest.raises(ValueError):
        load_wire('{"action":"a","action":"b","parameters":[]}', 6)


def test_duplicate_parameters_are_reported_at_named_field_without_renaming():
    wire = encode(fixtures()[1]); op = wire['phaseRows'][0][9]
    op['parameters'] = [{'name': 'metric', 'type': 'choice', 'value': 'psnr'},
                        {'name': 'metric', 'type': 'choice', 'value': 'storage'}]
    before = deepcopy(wire); feedback = field_feedback(wire)
    assert any(x['path'] == '/phaseRows/0/9/parameters/1/name' for x in feedback['issues'])
    assert wire == before
