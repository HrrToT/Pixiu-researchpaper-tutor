"""Bound existing references without choosing evidence or fixing model output."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_revision_sources as sources
from services.deep_research.workflow_revision_context import guidance, completion_guidance
from services.deep_research.workflow_metadata_repair import prepare
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import dispatch_options, overhead_bytes
from services.deep_research.contracts import DeepResearchError
from llm.responses_transport import payload
from test_deep_research_workflow_revision_context import record as legacy
from test_deep_research_workflow_revision_input import failed, StopBeforeProvider


def record(): return {**legacy(), 'workflowRevisionContextContractVersion': 3}


@pytest.mark.parametrize('refs', [['E1', 'E5'], []])
def test_only_valid_unchanged_sources_are_bound(refs):
    wire = {'sourceRefs': refs}; before = deepcopy(wire)
    result = sources.bound_refs(record(), wire, {'issues': [], 'codes': ['timeline.input.group_leak']}, {'E1': 'x', 'E5': 'y'})
    assert result == refs and wire == before
    result.append('E20'); assert wire == before


@pytest.mark.parametrize('refs', [None, True, ['E1', 'E1'], ['E999'], [5]])
def test_invalid_or_unpermitted_source_lists_are_never_frozen(refs):
    assert sources.bound_refs(record(), {'sourceRefs': refs}, {'issues': []}, {'E1': 'x'}) is None


@pytest.mark.parametrize('feedback', [{'issues': [{'path': '/sourceRefs/0'}]}, {'codes': ['unit.sourceRefs'], 'issues': []}])
def test_a_diagnosed_source_error_retains_model_authored_source_repair(feedback):
    assert sources.bound_refs(record(), {'sourceRefs': ['E1']}, feedback, {'E1': 'x'}) is None


@pytest.mark.parametrize('marker', [None, True, False, 0, 1, 2, 4, '3'])
def test_old_and_invalid_profiles_cannot_bind_sources(marker):
    assert sources.bound_refs({**record(), 'workflowRevisionContextContractVersion': marker}, {'sourceRefs': ['E1']}, {}, {'E1': 'x'}) is None


def test_native_schema_binds_exact_reference_array_without_modifying_base_descriptor():
    from services.deep_research.workflow_metadata_symbols import descriptor
    base = descriptor(); before = deepcopy(base)
    bound = sources.bind_descriptor(base, ['E1', 'E5'])
    assert base == before and bound['schema']['properties']['sourceRefs']['const'] == ['E1', 'E5']
    expected = deepcopy(base); expected['name'] = sources.NAME
    expected['schema']['properties']['sourceRefs']['const'] = ['E1', 'E5']
    assert bound == expected


def test_actual_responses_payload_keeps_binding_internal_and_accounts_for_schema_size():
    req = request_identity(record(), 'repair_workflow_meta', 'complete proposal', {sources.OPTION: ['E1', 'E5']})
    opts = req['extra']; wire = payload(req['messages'], opts, model='fixture', temperature=0)
    assert sources.OPTION not in wire and wire['text']['format']['schema']['properties']['sourceRefs']['const'] == ['E1', 'E5']
    assert wire['max_output_tokens'] == 6144
    size = len(json.dumps({'_deepseek_api': 'responses', 'response_format': opts['response_format']}, ensure_ascii=False, separators=(',', ':')).encode())
    assert overhead_bytes(record(), 'repair_workflow_meta', opts) == size
    tampered = deepcopy(opts); tampered[sources.OPTION] = ['E2']
    with pytest.raises(ValueError, match='source binding'): payload(req['messages'], tampered, model='fixture', temperature=0)


@pytest.mark.parametrize('node', ['plan_workflow_meta', 'plan_workflow_init', 'plan_experiment_outline'])
def test_unrelated_nodes_cannot_enable_reference_binding(node):
    with pytest.raises(ValueError): request_identity(record(), node, 'complete', {sources.OPTION: ['E1']})


def test_fitting_rule_and_decoder_rule_are_explicit_without_chosen_group_values():
    text = guidance(record(), {'issues': []})
    assert 'EVERY group' in text and 'intervention-off' in text and 'paired finite budgets' in text
    assert 'ONLY while restoring' in completion_guidance(record())
    assert completion_guidance(legacy()) == ''


def test_production_prepare_rejects_changed_valid_source_instead_of_correcting_it():
    w, unit = failed(); aliases = {x: x for x in w['sourceRefs']}; original = deepcopy(unit)
    changed = deepcopy(w); changed['sourceRefs'] = [] if w['sourceRefs'] else ['E999']
    response = {'content': json.dumps(changed), 'finishReason': 'stop'}
    saved = []; invoke = Mock(return_value=response)
    with pytest.raises(DeepResearchError):
        prepare(record(), source_data=json.dumps({'question': 'retain complete experiment'}), failed=unit,
                aliases=aliases, existing=None, invoke=invoke, checkpoint=saved.append)
    assert unit == original and invoke.call_count == 1
    assert saved[-1]['status'] == 'invalid_response' and 'unit.sourceRefs.changed' in saved[-1]['errors']
    assert saved[-1]['response'] == response
    assert saved[-1]['request']['extra'][sources.OPTION] == w['sourceRefs']
    no_send = Mock()
    with pytest.raises(DeepResearchError):
        prepare(record(), source_data=json.dumps({'question': 'retain complete experiment'}), failed=unit,
                aliases=aliases, existing=saved[-1], invoke=no_send, checkpoint=lambda _: None)
    no_send.assert_not_called()


def test_pending_legacy_request_cannot_be_reinterpreted_as_bound_source_revision():
    w, unit = failed(); aliases = {x: x for x in w['sourceRefs']}; saved = []
    with pytest.raises(StopBeforeProvider):
        prepare(legacy(), source_data='{}', failed=unit, aliases=aliases, existing=None,
                invoke=Mock(side_effect=StopBeforeProvider()), checkpoint=saved.append)
    no_send = Mock()
    with pytest.raises(DeepResearchError, match='身份或状态'):
        prepare(record(), source_data='{}', failed=unit, aliases=aliases, existing=saved[-1], invoke=no_send, checkpoint=lambda _: None)
    no_send.assert_not_called()


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_bound_sources_reach_http_with_budget_and_unknown_safeguards(tmp_path, monkeypatch, scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError, UnresolvedUnknownError, digest
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r = record(); r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    post = Mock(side_effect=requests.ReadTimeout('unknown')) if scenario == 'unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post', post)
    client = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    reserve = Mock(side_effect=BudgetExhaustedError('tokens', 100001, 100000)) if scenario == 'budget' else Mock(wraps=repo.reserve_call)
    tracked = TrackedLLMInvoker(client, reserve, repo.complete_call, request_options=research_model_options,
        run_record_fn=repo.require_run, workflow_revision_context_max_input_bytes=64000)
    req = request_identity(r, 'repair_workflow_meta', 'complete public proposal', {sources.OPTION: ['E1', 'E5']})
    def run(): return tracked('r', 'repair_workflow_meta', req['prompt'], dispatch_options(r, 'repair_workflow_meta', req['extra']), use_reserve=True)
    if scenario == 'budget':
        with pytest.raises(BudgetExhaustedError): run()
        post.assert_not_called(); return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises((UnknownCallError, UnresolvedUnknownError)): run()
    else: run()
    assert post.call_count == 1 and repo.list_calls('r')[0]['argsDigest'] == digest(req)
    wire = post.call_args.kwargs['json']
    assert sources.OPTION not in wire and wire['text']['format']['schema']['properties']['sourceRefs']['const'] == ['E1', 'E5']
    assert wire['max_output_tokens'] == 6144 and post.call_args.kwargs['timeout'] == 90
