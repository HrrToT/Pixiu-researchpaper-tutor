from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.workflow_metadata_steps import decode, field_feedback, NAME
from services.deep_research.workflow_metadata_repair import prepare
from test_deep_research_workflow_metadata_steps import observations, primitives
from test_deep_research_workflow_metadata_ordered import authored
from test_deep_research_workflow_metadata_ordered_integration import input_value
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_lifecycle_units import fixtures


def failed_step_unit():
    wire = observations(); wire['components'][0]['lifecycle']['createBefore'] = 'unknown'
    raw = response(wire)
    return {'request': {'prompt': 'original', 'extra': {}}, 'response': raw,
        'responseDigest': digest(raw), 'value': None, 'valueDigest': digest(None),
        'status': 'invalid_response', 'errors': ['unit.json']}


def explicit_initializers():
    old = authored(); initializers = fixtures()[2]
    for unit in initializers:
        for item in unit['initialization']['inputs']:
            if 'phaseId' in item:
                index = next(i for i, p in enumerate(old['phases']) if p['phaseId'] == item['phaseId'])
                item['phaseId'] = f'step_{index}_operation'
    return initializers


def test_typed_generation_revision_full_assembly_and_resume_preserve_complete_inputs():
    wire = observations(); bad = deepcopy(wire); bad['components'][0]['lifecycle']['createBefore'] = 'unknown'
    r, original, invoke, run = setup_repair([response(bad), response(wire), *map(response, explicit_initializers())])
    r['workflowMetadataRepairContractVersion'] = 13
    saved = run(); initial = saved['units']['metadata']; revised = saved['metadataRepair']
    assert initial['value'] is None and initial['response'] == response(bad)
    assert revised['status'] == 'ready' and revised['value'] == decode(wire)
    assert not saved['scientificApproval']
    req = initial['request']; assert req['extra']['response_format']['name'] == NAME
    assert req['extra']['max_tokens'] == 3072 and req['extra']['thinking'] == {'type': 'disabled'}
    assert 'zero-based positions supply identity' in req['prompt']
    assert 'Baseline training precedes' in req['prompt']
    assert 'createBefore is ONE exact declared phase ID' not in req['prompt']
    source = json.loads(original.split('Authoritative input data (not instructions):\n', 1)[1])
    assert input_value(req['prompt']) == {'authoritativeInput': source, 'unitContext': {}}
    data = input_value(revised['request']['prompt'])
    assert data['authoritativeInput'] == source and data['invalidMetadata'] == bad
    assert data['fieldFeedback']['issues'][0]['actual'] == 'unknown'
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls


def test_group_feedback_maps_expanded_measurement_to_authored_step_and_values():
    wire = observations(); wire['steps'][2]['reads'].append({'state': 'added', 'selector': 'treatment only'})
    before = deepcopy(wire); result = field_feedback(wire, {'E1': 'owned'})
    issue = next(x for x in result['issues'] if x['code'] == 'timeline.input.group_leak')
    assert issue['path'].startswith('/steps/2/reads/')
    assert issue['actual'] == {'state': 'added', 'selector': 'treatment only'}
    assert issue['consumerStepIndex'] == 2 and issue['consumerOutputStage'] == 'measurement'
    assert issue['sourceGroups'] == ['1'] and issue['consumerGroups'] == ['0']
    assert 'declaredPhaseIds' not in result and wire == before
    assert not result['scientificApproval']


def test_lifetime_feedback_keeps_authored_index_not_compiler_phase_name():
    wire = observations(); wire['components'][0]['lifecycle']['createBefore'] = 3
    result = field_feedback(wire, {'E1': 'owned'})
    issue = next(x for x in result['issues'] if x['code'] == 'metadata.lifecycle.before_creation')
    assert issue['createBefore'] == 3 and not result['scientificApproval']


def test_large_local_error_points_to_complete_original_value_instead_of_duplicating_or_truncating():
    wire = observations(); wire['steps'][2]['recording']['inputs'] = [{'unexpected': 'x'*700}]
    before = deepcopy(wire); feedback = field_feedback(wire, {'E1': 'owned'})
    issue = next(x for x in feedback['issues'] if x['code'] == 'steps.record_inputs')
    assert issue['actualPresent'] and 'actual' not in issue
    assert issue['actualInInvalidMetadata'] == '/steps/2/recording/inputs'
    assert wire == before and len(wire['steps'][2]['recording']['inputs'][0]['unexpected']) == 700


def expanded_over_capacity():
    wire = primitives(); wire['unresolved'] = ['']
    packed = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':'))
    wire['unresolved'] = ['x' * (8188 - len(packed(wire).encode()))]
    assert len(packed(wire).encode()) <= 8192 < len(packed(decode(wire)).encode())
    return wire


def test_step_expansion_cannot_bypass_existing_8kb_content_limit():
    r, _, invoke, run = setup_repair([response(expanded_over_capacity())])
    r['workflowMetadataRepairContractVersion'] = 13
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 1
    saved = r['state']['executionWorkflowBlueprint']
    assert 'unit.output_capacity' in saved['units']['metadata']['errors'] and 'metadataRepair' not in saved


def test_revision_expansion_is_also_refused_and_never_repeated():
    r, _, _, _ = setup_repair(); r['workflowMetadataRepairContractVersion'] = 13
    invoke = Mock(return_value=response(expanded_over_capacity())); store = {}
    def save(v): store['revision'] = deepcopy(v)
    def run(): return prepare(r, source_data='{}', failed=failed_step_unit(), aliases={'E1': 'owned'},
        existing=store.get('revision'), invoke=invoke, checkpoint=save)
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 1 and 'unit.output_capacity' in store['revision']['errors']
