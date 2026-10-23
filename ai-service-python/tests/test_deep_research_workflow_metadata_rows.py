"""Wire round trips retain complete metadata and existing rejection semantics."""
from copy import deepcopy
import json

import pytest

from services.deep_research.contracts import digest
from services.deep_research.workflow_metadata_rows import encode, decode, descriptor, POLICY
from services.deep_research.workflow_units import unit_errors, descriptor as unit_descriptor, META
from test_deep_research_workflow_lifecycle_units import fixtures


def test_complete_metadata_round_trip_keeps_values_validation_and_input_ownership():
    _, meta, _ = fixtures()
    original = deepcopy(meta)
    wire = encode(meta)
    restored = decode(wire)
    assert digest(restored) == digest(original)
    assert digest(encode(restored)) == digest(wire)
    assert unit_errors(restored, {'E1': 'owned'}, node=META, version=7) == []
    assert len(json.dumps(wire).encode('utf8')) < len(json.dumps(meta).encode('utf8'))
    restored['components'][0]['lifecycle']['createAfter'].append('mutated')
    assert meta == original and encode(original) == wire


@pytest.mark.parametrize('change', ['unknown', 'missing', 'component_arity', 'phase_arity',
    'lifecycle_arity', 'read_arity', 'action_arity', 'parameter_arity', 'rows_type'])
def test_malformed_wire_is_rejected_without_guessing_or_dropping_fields(change):
    wire = encode(fixtures()[1])
    if change == 'unknown': wire['extra'] = 'must not disappear'
    elif change == 'missing': del wire['sourceRefs']
    elif change == 'component_arity': wire['componentRows'][0].append('extra')
    elif change == 'phase_arity': wire['phaseRows'][0].pop()
    elif change == 'lifecycle_arity': wire['componentRows'][0][2].pop()
    elif change == 'read_arity': wire['phaseRows'][0][6] = [['state']]
    elif change == 'action_arity': wire['phaseRows'][0][9].append('extra')
    elif change == 'parameter_arity': wire['phaseRows'][0][9][1] = [['name', 'number']]
    elif change == 'rows_type': wire['componentRows'] = {}
    with pytest.raises(ValueError): decode(wire)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), ('tuple',), {1: 'key'}, {'set'}])
def test_non_json_values_cannot_be_coerced(value):
    meta = fixtures()[1]
    meta['unresolved'] = value
    with pytest.raises(ValueError): encode(meta)


def test_invalid_phase_dependency_is_preserved_for_semantic_rejection():
    meta = fixtures()[1]
    meta['components'][0]['lifecycle']['createAfter'] = ['not_a_declared_phase']
    before = unit_errors(meta, {'E1': 'owned'}, node=META, version=7)
    after = decode(encode(meta))
    assert before and unit_errors(after, {'E1': 'owned'}, node=META, version=7) == before
    assert after == meta


def test_bool_number_unicode_null_and_reference_variants_keep_their_types():
    meta = fixtures()[1]
    meta['frameIterations'] = True  # Invalid integer semantics must not be normalized to 1.
    meta['phases'][0]['action']['parameters'] = [
        {'name': '整数', 'type': 'number', 'value': 3},
        {'name': 'float', 'type': 'number', 'value': 3.0},
        {'name': 'invalid_bool', 'type': 'number', 'value': False}]
    meta['phases'][0]['reads'] = [
        {'state': 'baseline', 'selector': '完整状态'},
        {'phaseId': 'x', 'outputId': 'y', 'selector': 'z'}]
    assert digest(decode(encode(meta))) == digest(meta)


def test_canonical_unknown_nested_fields_cannot_be_silently_dropped():
    meta = fixtures()[1]
    meta['phases'][0]['action']['parameters'] = [
        {'name': 'steps', 'type': 'number', 'value': 1, 'extra': 'retain or reject'}]
    with pytest.raises(ValueError): encode(meta)


def test_schema_keeps_original_bounds_and_does_not_mutate_legacy_descriptors():
    old = unit_descriptor(META, 7)
    old_digest = digest(old)
    wire = descriptor()['schema']
    assert digest(unit_descriptor(META, 7)) == old_digest
    assert set(wire['required']) == set(wire['properties'])
    assert wire['properties']['componentRows']['maxItems'] == old['schema']['properties']['components']['maxItems']
    assert wire['properties']['phaseRows'] == old['schema']['properties']['phases']
    for name, count in [('phase', 11), ('lifecycle', 3), ('operation', 2)]:
        assert wire['$defs'][name]['minItems'] == wire['$defs'][name]['maxItems'] == count
    assert 'phase IDs only' in POLICY and 'reserved complete baseline' in POLICY
    assert digest(unit_descriptor(META, 6)) == '89f2f751877e93814cdfbc28cd2c7ea2ba71140d7238e177087d7c19ce133608'


def rows_setup(meta=None):
    from test_deep_research_workflow_lifecycle_units import setup
    _, canonical, inits = fixtures()
    wire = encode(canonical if meta is None else meta)
    r, prompt, invoke, run = setup()
    r['workflowMetadataRowsContractVersion'] = 1
    invoke.side_effect = [{'content': json.dumps(v), 'finishReason': 'stop'} for v in [wire, *inits]]
    return r, prompt, invoke, run


def test_versioned_pipeline_retains_original_wire_and_assembles_the_same_workflow():
    from services.deep_research.planning_transport import descriptor_for
    from services.deep_research.workflow_units import INIT
    r, _, invoke, run = rows_setup()
    saved = run()
    expected, meta, _ = fixtures()
    expected['records'] = saved['value']['workflow']['records']
    assert saved['value']['workflow'] == expected
    assert saved['units']['metadata']['value'] == meta
    assert json.loads(saved['units']['metadata']['response']['content']) == encode(meta)
    assert saved['request']['metadataRowsContract'] == 1 and not saved['scientificApproval']
    assert descriptor_for(r, META) == descriptor()
    assert descriptor_for(r, INIT) == unit_descriptor(INIT, 7)
    assert 'workflow_metadata_rows_v1' in invoke.call_args_list[0].args[1]
    assert 'createAfter and disposeAfter reference phase IDs only' in invoke.call_args_list[0].args[1]
    assert run() == saved and invoke.call_count == 4


@pytest.mark.parametrize('mutation', ['raw', 'expanded', 'wire_contract'])
def test_resuming_changed_wire_value_or_contract_never_triggers_a_new_call(mutation):
    from services.deep_research.contracts import DeepResearchError
    r, _, invoke, run = rows_setup()
    run()
    unit = r['state']['executionWorkflowBlueprint']['units']['metadata']
    if mutation == 'raw': unit['response']['content'] += ' '
    elif mutation == 'expanded': unit['value']['frameIterations'] += 1
    else: del r['workflowMetadataRowsContractVersion']
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_blueprint_state' and invoke.call_count == 4


@pytest.mark.parametrize('mutation', ['dependency', 'arity', 'truncated', 'old_object', 'wire_capacity'])
def test_invalid_wire_cannot_be_repaired_or_resent_implicitly(mutation):
    from services.deep_research.contracts import DeepResearchError
    r, _, invoke, run = rows_setup()
    wire = encode(fixtures()[1])
    finish = 'stop'
    if mutation == 'dependency': wire['componentRows'][0][2][1] = ['not_a_phase']
    elif mutation == 'arity': wire['phaseRows'][0].pop()
    elif mutation == 'truncated': finish = 'length'
    elif mutation == 'old_object': wire = fixtures()[1]
    else: wire['phaseRows'][0][9][0] = 'x' * 8200
    raw = json.dumps(wire)
    invoke.side_effect = [{'content': raw, 'finishReason': finish}]
    for _ in range(2):
        with pytest.raises(DeepResearchError) as exc: run()
        assert exc.value.code == 'invalid_workflow_unit_response'
    assert invoke.call_count == 1
    saved = r['state']['executionWorkflowBlueprint']
    assert saved['units']['metadata']['response']['content'] == raw
    assert saved['status'] == 'pending' and not saved['scientificApproval']


def test_legacy_record_keeps_exact_prompt_request_schema_and_no_rows_identity():
    from services.deep_research.planning_transport import descriptor_for
    from test_deep_research_workflow_lifecycle_units import setup
    from services.deep_research.workflow_metadata_rows import enabled
    r, _, invoke, run = setup()
    saved = run()
    assert not enabled(r) and 'metadataRowsContract' not in saved['request']
    assert descriptor_for(r, META) == unit_descriptor(META, 7)
    assert 'workflow_metadata_rows_v1' not in invoke.call_args_list[0].args[1]
    for wrong in (True, 0, 3, '1', None):
        assert not enabled({**r, 'workflowMetadataRowsContractVersion': wrong})


def test_expansion_has_its_own_cap_without_increasing_the_original_response_cap():
    meta = fixtures()[1]
    meta['phases'][0]['action']['parameters'] = [
        {'name': 'parameter_' + str(i), 'type': 'number', 'value': i} for i in range(120)]
    packed = lambda v: json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    assert len(packed(encode(meta))) < 8192 < len(packed(meta)) < 32000
    assert unit_errors(meta, {'E1': 'owned'}, node=META, version=7) == ['unit.output_capacity']
    r, _, _, run = rows_setup(meta)
    saved = run()
    assert saved['units']['metadata']['value'] == meta and not saved['scientificApproval']
    oversized = deepcopy(meta)
    oversized['phases'][0]['action']['action'] = 'x' * 32000
    assert 'unit.output_capacity' in unit_errors(oversized, {'E1': 'owned'}, node=META,
                                               version=7, metadata_rows=True)


@pytest.mark.parametrize('replacement', [None, True, 2])
def test_contract_marker_is_immutable_and_cannot_opt_old_records_in(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    r, _, _, _ = rows_setup()
    r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path/'marker.sqlite3')
    repo.initialize(); repo.create_run(r)
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run('r', lambda x: {**x, 'workflowMetadataRowsContractVersion': replacement})
    old = deepcopy(r)
    old.update(runId='old', idempotencyKey='old')
    del old['workflowMetadataRowsContractVersion']
    repo.create_run(old)
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run('old', lambda x: {**x, 'workflowMetadataRowsContractVersion': 1})


def test_client_cannot_override_the_server_rows_contract(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.workflow_metadata_rows import enabled
    repo = DeepResearchRepository(tmp_path/'api.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        row, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'fixture',
            'question': 'Design', 'workflowMetadataRowsContractVersion': 2,
            'deferStart': True}, start_async=False)
        assert row['workflowMetadataRowsContractVersion'] == 1 and enabled(row)
    finally:
        facade.shutdown()


def test_v2_policy_preserves_v1_text_and_wire_but_clarifies_actual_state_and_reads():
    import hashlib
    from services.deep_research.workflow_metadata_rows import policy_for
    from services.deep_research.planning_transport import descriptor_for
    assert hashlib.sha256(policy_for(1).encode('utf8')).hexdigest() == (
        '70d26ac8827ce9894f10ad22650ceffebc2a07ec69da905af32543c2344a64b3')
    assert policy_for(2).startswith(policy_for(1))
    assert 'never a bare string' in policy_for(2)
    assert 'do not omit any required model tensors, optimizer state or carried temporal state' in policy_for(2)
    assert 'one minified JSON object' in policy_for(2)
    r, _, _, _ = rows_setup()
    assert descriptor_for(r, META) == descriptor_for({**r, 'workflowMetadataRowsContractVersion': 2}, META)
    for invalid in (True, None, 0, 3, '2'):
        with pytest.raises(ValueError): policy_for(invalid)


def test_v2_keeps_complete_assembly_and_cannot_reinterpret_v1_saved_requests():
    from services.deep_research.contracts import DeepResearchError
    r, _, invoke, run = rows_setup()
    r['workflowMetadataRowsContractVersion'] = 2
    saved = run()
    assert saved['request']['metadataRowsContract'] == 2
    assert 'one minified JSON object' in invoke.call_args_list[0].args[1]
    expected, _, _ = fixtures()
    expected['records'] = saved['value']['workflow']['records']
    assert saved['value']['workflow'] == expected and not saved['scientificApproval']
    assert run() == saved and invoke.call_count == 4
    r['workflowMetadataRowsContractVersion'] = 1
    with pytest.raises(DeepResearchError) as exc: run()
    assert exc.value.code == 'invalid_workflow_blueprint_state' and invoke.call_count == 4


def test_v2_prompt_keeps_every_authoritative_value_and_does_not_select_defaults():
    from services.deep_research.workflow_units import unit_prompt
    from services.deep_research.nested_tables import unpack
    source = {'question': 'original objective', 'evidence': [{'quote': '完整原文', 'id': 'E1'}],
              'tables': [{'value': 0.00015}], 'requirements': ['all required measurements']}
    context = {'userChoice': 'unchanged'}
    for version in (1, 2):
        prompt = unit_prompt(json.dumps(source, ensure_ascii=False), node=META, context=context,
                             version=7, metadata_rows=True, metadata_rows_contract=version)
        wire = prompt.split('Exact authoritative input and unit context (unverified data):\n', 1)[1]
        values = unpack(json.loads(wire.split('\nInput encoding only:', 1)[0]))
        assert values == {'authoritativeInput': source, 'unitContext': context}
