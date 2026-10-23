import json
from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.workflow_transport import descriptor, enabled
from services.deep_research.planning_transport import overhead_bytes, options_for_record
from services.deep_research.execution_workflow_blueprint import prepare, prompt_for
from test_deep_research_execution_workflow_blueprint import record, value
from services.deep_research.contracts import DeepResearchError, digest


def current():
    r = record(); r['executionWorkflowContractVersion'] = 3
    return r


def test_schema_references_resolve_and_operation_rules_require_parameters():
    schema = descriptor()['schema']
    def visit(item):
        if isinstance(item, dict):
            if '$ref' in item:
                assert item['$ref'].startswith('#/$defs/')
                assert item['$ref'][8:] in schema['$defs']
            for child in item.values(): visit(child)
        elif isinstance(item, list):
            for child in item: visit(child)
    visit(schema)
    assert schema['additionalProperties'] is False
    assert schema['$defs']['rule']['properties']['parameters']['minItems'] == 1
    assert 'minItems' not in schema['$defs']['operation']['properties']['parameters']
    assert schema['properties']['workflow']['additionalProperties'] is False


@pytest.mark.parametrize('version', [None, True, '3', 1, 2, 5])
def test_schema_transport_does_not_change_old_workflow_versions(version):
    r = current(); r['executionWorkflowContractVersion'] = version
    assert not enabled(r, 'plan_workflow')
    assert options_for_record(r, 'plan_workflow', {})['response_format'] == {'type': 'json_object'}


def test_schema_capacity_stops_before_invocation_and_preserves_failed_input():
    r = current(); extra = overhead_bytes(r, 'plan_workflow'); saved = []; invoke = Mock()
    prompt = 'x' * (32001-extra)
    with pytest.raises(DeepResearchError) as e:
        prepare(r, prompt=prompt, aliases={}, invoke=invoke, parse=json.loads, checkpoint=saved.append)
    assert e.value.code == 'workflow_blueprint_input_capacity'
    assert saved[-1]['inputBytes'] == 32001
    assert saved[-1]['request']['prompt'] == prompt
    invoke.assert_not_called()


def test_schema_prompt_keeps_exact_source_data_and_separates_fitting_from_initialization():
    args = dict(question='原始问题', basis={'value': 'unchanged'}, sources={},
                evidence=[{'quote': 'steps executionSpec exactly'}], tables={}, obligations=[])
    old = prompt_for(**args, version=2).split('Authoritative input data (not instructions):\n')[1]
    new = prompt_for(**args, version=3)
    assert new.split('Authoritative input data (not instructions):\n')[1] == old
    assert 'a training procedure is not an initializer' in new


@pytest.mark.parametrize('version', [3, 4])
def test_workflow_frozen_identity_matches_real_http_schema_and_resumes(tmp_path, monkeypatch, version):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    r = current(); r.update(runId='r', taskId='t', executionWorkflowContractVersion=version)
    repo.create_run(r); repo.begin_execution('r')
    raw = json.dumps(value()); post = Mock(return_value=response(raw))
    monkeypatch.setattr('llm.client.requests.post', post)
    provider = DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')
    scoped = ScopedModelClient(repo, lambda *a: True, lambda: provider).for_run('r')
    reserve = Mock(wraps=repo.reserve_call)
    invoke = TrackedLLMInvoker(scoped, reserve, repo.complete_call,
        request_options=research_model_options, run_record_fn=repo.require_run)
    def checkpoint(v):
        repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'executionWorkflowBlueprint': deepcopy(v)}})
    def run():
        return prepare(repo.require_run('r'), prompt='exact source', aliases={'E1':'owned'},
            invoke=lambda node,prompt,opts:invoke('r',node,prompt,opts,use_reserve=True),
            parse=json.loads, checkpoint=checkpoint)
    result = run()
    assert result['status'] == 'ready' and result['scientificApproval'] is False
    assert repo.list_calls('r')[0]['argsDigest'] == digest(result['request'])
    assert post.call_args.args[0].endswith('/responses')
    assert post.call_args.kwargs['json']['text']['format'] == descriptor(version)
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == len('exact source')+1024+overhead_bytes(r,'plan_workflow')+6144
    assert run() == result and post.call_count == 1


def test_v4_records_preserve_every_required_output_and_v3_fingerprint():
    from services.deep_research.experiment_workflow import RECORDS
    assert digest(descriptor(3)) == '35242c8e9a760e8fdb791060cbfb4c8d21045bd416f0e7e294559f5487b2ad69'
    required = descriptor(4)['schema']['properties']['workflow']['properties']['records']['items']['enum']
    assert len(required) == len(set(required)) == 9
    assert set(required) == RECORDS | {'group_checkpoints'}
    before = descriptor(3); after = descriptor(4)
    after['name'] = before['name']
    after['schema']['properties']['workflow']['properties']['records'] = before['schema']['properties']['workflow']['properties']['records']
    assert before == after


def test_v4_locally_rejects_extra_record_names_without_rewriting_response():
    from services.deep_research.execution_workflow_blueprint import errors
    v = value()
    v['workflow']['records'] = descriptor(4)['schema']['properties']['workflow']['properties']['records']['items']['enum'] + ['timing_policy_treatment']
    before = deepcopy(v)
    assert 'blueprint.records' in errors(v, {'E1': 'owned'}, version=4)
    assert 'blueprint.records' not in errors(v, {'E1': 'owned'}, version=3)
    assert v == before


def test_v4_record_order_is_irrelevant_but_missing_or_repeated_categories_fail():
    from services.deep_research.execution_workflow_blueprint import errors
    v = value(); records = descriptor(4)['schema']['properties']['workflow']['properties']['records']['items']['enum']
    v['workflow']['records'] = list(reversed(records))
    assert not errors(v, {'E1':'owned'}, version=4)
    for broken in (records[:-1], records[:-1]+[records[0]]):
        v['workflow']['records'] = broken
        assert 'blueprint.records' in errors(v, {'E1':'owned'}, version=4)
