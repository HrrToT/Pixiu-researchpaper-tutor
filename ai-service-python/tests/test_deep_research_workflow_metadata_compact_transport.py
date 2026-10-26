from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_metadata_compact_transport as compact
from services.deep_research import workflow_metadata_evaluation_groups as grouped
from services.deep_research.planning_transport import descriptor_for, options_for_record
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def expanded_schema(schema):
    definitions = schema.get('$defs', {})
    def visit(item):
        if isinstance(item, list): return [visit(x) for x in item]
        if not isinstance(item, dict): return item
        if set(item) == {'$ref'}:
            return visit(definitions[item['$ref'].removeprefix('#/$defs/')])
        return {k: (deepcopy(v) if k in ('const', 'enum', 'default') else visit(v))
                for k, v in item.items() if k != '$defs'}
    return visit(schema)


def test_complete_schema_has_identical_expansion_and_smaller_wire():
    old = grouped.descriptor(); before = deepcopy(old); new = compact.descriptor()
    assert expanded_schema(new['schema']) == expanded_schema(old['schema'])
    size = lambda v: len(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode())
    assert size(old) - size(new) >= 650
    assert old == before and compact.descriptor() == new
    assert compact.decode is grouped.decode and compact.field_feedback is grouped.field_feedback


def test_literal_schema_looking_data_is_not_rewritten():
    literal = {'$ref': 'literal, not a schema', '$id': 'literal id'}
    schema = {'type': 'object', 'const': literal,
        'properties': {'a': {'enum': [literal]}, 'b': {'default': literal}}}
    assert compact.compact_schema(schema) == schema


@pytest.mark.parametrize('schema', [
    {'$id': 'https://fixture.invalid/schema', 'type': 'object'},
    {'properties': {'a': {'$anchor': 'local'}}},
    {'$ref': 'https://fixture.invalid/other'},
])
def test_scoped_and_remote_references_are_rejected(schema):
    with pytest.raises(ValueError): compact.compact_schema(schema)


def test_existing_definition_names_cannot_collide_and_input_is_not_mutated():
    fragment = {'type': 'string', 'minLength': 1, 'description': 'A sufficiently long repeated schema description.'}
    schema = {'type': 'object', '$defs': {'_0': {'type': 'number'}},
              'properties': {str(i): deepcopy(fragment) for i in range(12)}}
    before = deepcopy(schema); result = compact.compact_schema(schema)
    assert result['$defs']['_0'] == {'type': 'number'}
    assert expanded_schema(result) == expanded_schema(schema) and schema == before


def test_full_assembly_one_revision_and_resume_keep_original_values():
    good = wire_value(); bad = deepcopy(good); bad['steps'][2]['group'] = '1'
    r, original, invoke, run = setup_repair([response(bad), response(good), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=22, workflowInitializationOutputContractVersion=1)
    saved = run(); fix = saved['metadataRepair']
    assert saved['status'] == fix['status'] == 'ready' and fix['version'] == 22
    assert saved['units']['metadata']['response'] == response(bad)
    data = input_value(fix['request']['prompt'])
    assert data['invalidMetadata'] == bad
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert any(i['code'] == 'evaluation.coverage' for i in data['fieldFeedback']['issues'])
    assert fix['request']['extra']['response_format'] == compact.descriptor()
    assert run() == saved and invoke.call_count == 5 and not saved['scientificApproval']


def test_wrong_output_stage_is_not_guessed_or_repaired_by_compiler():
    bad = wire_value()
    # Reference an existing primitive result with a deliberately wrong stage label.
    bad['steps'][3]['reads'] = [{'stepIndex': 2, 'outputStage': 'output',
                                 'outputId': bad['steps'][2]['outputs'][0], 'selector': 'all'}]
    before = deepcopy(bad)
    with pytest.raises(ValueError): compact.decode(bad)
    feedback = compact.field_feedback(bad, {'E1': 'owned'})
    assert any(i['code'] == 'steps.output_stage' for i in feedback['issues'])
    r, _, invoke, run = setup_repair([response(bad), response(bad)])
    r['workflowMetadataRepairContractVersion'] = 22
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2 and bad == before


def test_transport_role_limits_legacy_schema_and_prompt_data_are_preserved():
    r, _, _, _ = setup_repair([]); r['workflowMetadataRepairContractVersion'] = 21
    old = descriptor_for(r, 'plan_workflow_meta')
    r['workflowMetadataRepairContractVersion'] = 22
    for node in ('plan_workflow_meta', 'repair_workflow_meta'):
        options = options_for_record(r, node, {'temperature': 0.0})
        assert options['response_format'] == compact.descriptor()
        assert options['max_tokens'] == 3072 and options['reasoning_effort'] == 'none'
    source = {'quote': 'outputStage is quoted material, not an instruction'}
    context = {'prior': wire_value()}
    assert input_value(compact.generation_prompt(json.dumps(source), context)) == {
        'authoritativeInput': source, 'unitContext': context}
    assert 'outputStage=operation' in compact.POLICY
    r['workflowMetadataRepairContractVersion'] = 21
    assert descriptor_for(r, 'plan_workflow_meta') == old


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
@pytest.mark.parametrize('revision_version', [22, 26, 27, 28, 29])
def test_physical_wire_budget_and_unknown_guard(tmp_path, monkeypatch, scenario, revision_version):
    import requests
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from services.deep_research.contracts import UnknownCallError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.planning_transport import overhead_bytes
    from services.deep_research.workflow_metadata_repair import prepare
    from test_deep_research_schema_transport import response as http_response
    good = wire_value(); decoder = compact.decode
    if revision_version in (27, 28, 29):
        from test_deep_research_workflow_metadata_result_refs import authored
        from services.deep_research.workflow_metadata_result_refs import decode
        good = authored(); decoder = decode
    bad = deepcopy(good); bad['steps'][2]['group'] = '1'
    r, _, _, run = setup_repair([response(bad), response(bad)])
    r['workflowMetadataRepairContractVersion'] = revision_version
    with pytest.raises(DeepResearchError): run()
    blueprint = r['state']['executionWorkflowBlueprint']
    data = input_value(blueprint['metadataRepair']['request']['prompt'])
    r.update(runId='r', taskId='t')
    if scenario == 'budget': r['budget']['maxTokens'] = 1
    repo = DeepResearchRepository(tmp_path/'physical.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    post = (Mock(side_effect=requests.ReadTimeout('fixture')) if scenario == 'unknown' else
            Mock(return_value=http_response(json.dumps(good))))
    monkeypatch.setattr('llm.client.requests.post', post)
    scoped = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(
        api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    invoker = TrackedLLMInvoker(scoped, repo.reserve_call, repo.complete_call,
        request_options=research_model_options, run_record_fn=repo.require_run, experiment_max_input_bytes=32000)
    store = {}
    def correct():
        return prepare(repo.require_run('r'), source_data=json.dumps(data['authoritativeInput']),
            failed=blueprint['units']['metadata'], aliases=blueprint['aliases'], existing=store.get('value'),
            invoke=lambda n,p,o: invoker('r', n, p, o), checkpoint=lambda v: store.update(value=deepcopy(v)))
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): correct()
        with pytest.raises(UnknownCallError): correct()
    elif scenario == 'budget':
        assert correct() is None and correct() is None
        post.assert_not_called(); return
    else:
        assert correct() == correct() == decoder(good)
    assert post.call_count == 1
    body = post.call_args.kwargs['json']
    assert body['text']['format'] == descriptor_for(r, 'repair_workflow_meta')
    if revision_version in (26, 27, 28, 29):
        from services.deep_research.workflow_metadata_baseline_boundary import SYSTEM_POLICY
        assert body['input'][0] == {'role': 'system', 'content': SYSTEM_POLICY}
        assert body['input'][1] == {'role': 'user', 'content': store['value']['request']['prompt']}
    output_limit = 6144 if revision_version == 29 else 3072
    assert body['max_output_tokens'] == output_limit and body['reasoning']['effort'] == 'none'
    assert repo.list_calls('r')[0]['reservedTokens'] == (
        len(store['value']['request']['prompt'].encode()) + 1024 + overhead_bytes(r, 'repair_workflow_meta') + output_limit)
