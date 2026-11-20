from copy import deepcopy
import json

from services.deep_research import workflow_metadata_scope_end as scope
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps import primitives
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def test_native_delta_only_removes_duplicate_annotation_and_enforces_existing_readonly_rule():
    old = scope.descriptor(frame_count_rules=True); before = deepcopy(old)
    new = scope.descriptor(frame_count_rules=True, compact_rules=True)
    normalized = deepcopy(new); normalized['name'] = old['name']
    normalized['schema']['properties']['frameIterations']['description'] = scope.COUNT_POLICY.strip()
    for branch in normalized['schema']['$defs']['step']['anyOf']:
        kind = branch['properties']['kind']
        if kind.get('const') == 'record':
            assert branch['properties']['updates'] == {'const': []}
            original = next(x for x in old['schema']['$defs']['step']['anyOf'] if x['properties']['kind'] == kind)
            branch['properties']['updates'] = deepcopy(original['properties']['updates'])
        if 'evaluate' in kind.get('enum', []):
            assert branch.pop('allOf') == [{'if': {'properties': {'kind': {'const': 'evaluate'}}},
                                          'then': {'properties': {'updates': {'const': []}}}}]
    assert normalized == old and scope.descriptor(frame_count_rules=True) == before


def test_readonly_invalid_original_survives_one_revision_with_complete_inputs_and_resume():
    wire = authored(primitives); bad = deepcopy(wire); bad['steps'][4]['updates'] = ['ntc']
    assert 'timeline.phase.evaluation_updates' in unit_errors(scope.decode(bad), {'E1': 'owned'},
                                                             node=META, version=7, metadata_rows=True)
    r, original, invoke, run = setup_repair([response(bad), response(wire), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=17, workflowInitializationOutputContractVersion=1)
    saved = run(); revision = saved['metadataRepair']
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    assert saved['units']['metadata']['response'] == response(bad)
    data = input_value(revision['request']['prompt'])
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert data['invalidMetadata'] == bad and revision['response'] == response(wire)
    assert revision['request']['extra']['response_format']['name'] == 'typed_scope_release_steps_v3'
    assert scope.COUNT_POLICY in revision['request']['prompt']
    assert 'mutate states only in setup/fit' in revision['request']['prompt']
    assert run() == saved and invoke.call_count == 5


def test_compact_input_restores_all_values_and_changes_no_output_choices():
    data = {'question': 'Exact original', 'sources': [{'quote': 'complete quote', 'id': 'E1'}]}
    wire = authored(primitives); before = deepcopy(wire)
    prompt = scope.revision_prompt(json.dumps(data), wire, {'issues': []},
                                   frame_count_rules=True, compact_rules=True)
    restored = input_value(prompt)
    assert restored == {'authoritativeInput': data, 'invalidMetadata': wire, 'fieldFeedback': {'issues': []}}
    assert wire == before and scope.decode(wire) == scope.decode(before)
    assert len(scope.COMPACT_POLICY.encode()) < len(scope.POLICY.encode())
