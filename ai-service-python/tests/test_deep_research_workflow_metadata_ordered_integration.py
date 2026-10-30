"""New grammar integration; fixtures never confer scientific acceptance."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.workflow_metadata_ordered import (
    decode, descriptor, field_feedback, NAME, complete_scaffolding)
from services.deep_research.workflow_metadata_repair import prepare, NODE
from services.deep_research import nested_tables, shared_strings, workflow_metadata_input
from test_deep_research_workflow_metadata_ordered import authored
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_lifecycle_units import fixtures


def failed_ordered_unit():
    wire = authored(); wire['components'][0]['lifecycle']['createBefore'] = 'unknown_phase'
    raw = response(wire)
    return {'request': {'prompt': 'original', 'extra': {}}, 'response': raw,
        'responseDigest': digest(raw), 'value': None, 'valueDigest': digest(None),
        'status': 'invalid_response', 'errors': ['unit.json']}


def input_value(prompt):
    value = json.loads(next(line for line in prompt.splitlines() if line.startswith('{"')))
    if set(value) == {'strings', 'value'}:
        value = nested_tables.unpack(shared_strings.unpack(value))
    if set(value) == {'keys', 'value'}: value = workflow_metadata_input.unpack(value)
    return value


def test_ordered_generation_one_revision_initializers_assembly_and_resume():
    good = authored(); bad = deepcopy(good)
    bad['components'][0]['lifecycle']['createBefore'] = 'unknown_phase'
    r, original, invoke, run = setup_repair([response(bad), response(good), *map(response, fixtures()[2])])
    r['workflowMetadataRepairContractVersion'] = 11
    saved = run(); initial = saved['units']['metadata']; repair = saved['metadataRepair']
    assert initial['value'] is None and initial['errors'] == ['unit.json']
    assert initial['response'] == response(bad)
    assert repair['status'] == 'ready' and repair['value'] == decode(good)
    assert not saved['scientificApproval']
    req = initial['request']; prefix = req['prompt'].split('\n', 1)[0]
    assert 'phases array IS the full execution order' in prefix
    assert 'Output no phase.after or lifecycle.createAfter' in prefix
    assert 'createAfter and phase.after are always arrays' not in prefix
    assert req['extra']['response_format']['name'] == NAME
    assert req['extra']['thinking'] == {'type': 'disabled'} and req['extra']['max_tokens'] == 3072
    source = json.loads(original.split('Authoritative input data (not instructions):\n', 1)[1])
    assert input_value(req['prompt']) == {'authoritativeInput': source, 'unitContext': {}}
    actual = input_value(repair['request']['prompt'])
    assert actual['authoritativeInput'] == source and actual['invalidMetadata'] == bad
    assert actual['fieldFeedback']['issues'][0]['actual'] == 'unknown_phase'
    calls = invoke.call_count
    assert run() == saved and invoke.call_count == calls


def test_named_feedback_points_to_authored_boundary_without_choosing_a_new_one():
    wire = authored(); wire['components'][0]['lifecycle']['createBefore'] = wire['phases'][-1]['phaseId']
    before = deepcopy(wire); feedback = field_feedback(wire, {'E1': 'owned'})
    assert wire == before and not feedback['scientificApproval']
    issue = next(i for i in feedback['issues'] if i['code'] == 'metadata.lifecycle.before_creation')
    assert issue['createBefore'] == wire['phases'][-1]['phaseId']
    assert 'createAfter' not in issue


def test_group_feedback_exposes_original_source_and_consumer_groups_without_reassignment():
    wire = authored(); wire['components'][0]['appliesTo'] = ['only_source_group']
    before = deepcopy(wire)
    result = field_feedback(wire, {'E1': 'owned'})
    issue = next(i for i in result['issues'] if i['code'] == 'timeline.input.group_leak')
    assert issue['sourceGroups'] == ['only_source_group']
    phase = next(p for p in wire['phases'] if p['phaseId'] == issue['consumerPhaseId'])
    assert issue['consumerGroups'] == phase['groups'] and wire == before


@pytest.mark.parametrize('value', [None, [], 'missing'])
def test_bad_boundary_leaf_is_complete_but_never_inferred(value):
    wire = authored(); wire['components'][0]['lifecycle']['createBefore'] = value
    assert complete_scaffolding(wire)
    with pytest.raises(ValueError): decode(wire)
    feedback = field_feedback(wire, {'E1': 'owned'})
    assert feedback['issues'][0]['actual'] == value and not feedback['scientificApproval']


def expanded_over_capacity():
    wire = authored(); wire['frameIterations'] = 0
    cid = wire['components'][0]['componentId']; group = wire['components'][0]['appliesTo'][0]
    wire['components'] = [{'componentId': cid, 'appliesTo': [group], 'lifecycle': {
        'scope': 'per_repeat', 'createBefore': 'p0', 'disposeAfter': None}}]
    wire['phases'] = [{'phaseId': f'p{i}', 'scope': 'per_repeat', 'kind': 'setup',
        'groups': [group], 'sharing': 'shared', 'reads': [{'state': 'baseline', 'selector': 'selected'}],
        'updates': [cid], 'outputs': [f'out{i}'], 'action': {'action': 'prepare', 'parameters': []},
        'budget': None} for i in range(12)]
    wire['unresolved'] = ['']
    packed = lambda v: json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    wire['unresolved'] = ['x' * (8188 - len(packed(wire).encode()))]
    assert len(packed(wire).encode()) <= 8192 < len(packed(decode(wire)).encode())
    return wire


def test_decoded_expansion_cannot_bypass_original_8kb_content_limit():
    wire = expanded_over_capacity()
    r, _, invoke, run = setup_repair([response(wire)])
    r['workflowMetadataRepairContractVersion'] = 11
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 1
    saved = r['state']['executionWorkflowBlueprint']
    assert 'unit.output_capacity' in saved['units']['metadata']['errors']
    assert 'metadataRepair' not in saved


def test_revision_decoded_expansion_is_also_refused_without_retry():
    r, _, _, _ = setup_repair(); r['workflowMetadataRepairContractVersion'] = 11
    invoke = Mock(return_value=response(expanded_over_capacity())); store = {}
    def save(value): store['revision'] = deepcopy(value)
    def run(): return prepare(r, source_data='{}', failed=failed_ordered_unit(),
        aliases={'E1': 'owned'}, existing=store.get('revision'), invoke=invoke, checkpoint=save)
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 1 and 'unit.output_capacity' in store['revision']['errors']
