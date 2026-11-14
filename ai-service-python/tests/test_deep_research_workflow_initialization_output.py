from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests

from llm.client import DeepSeekLLM
from llm.provider import LLMProviderError
from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError, UnresolvedUnknownError
from services.deep_research.planning_transport import options_for_record, overhead_bytes
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.runtime import ScopedModelClient, research_model_options
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_scientific_outline import record
from test_deep_research_schema_transport import response as http_response
from test_deep_research_workflow_lifecycle_units import fixtures


MARKER = 'workflowInitializationOutputContractVersion'


@pytest.mark.parametrize('injected', [None, True, 999])
def test_new_marker_is_server_owned_and_client_cannot_override(tmp_path, injected):
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path/'profile.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        row, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'new', 'question': 'Design',
                                'deferStart': True, MARKER: injected}, start_async=False)
        assert type(row[MARKER]) is int and row[MARKER] == 1
    finally: facade.shutdown()


def current(marker=1):
    r = record(); r.update(runId='r', taskId='t', executionWorkflowContractVersion=7,
                          workflowMetadataRowsContractVersion=2, workflowMetadataRepairContractVersion=16)
    if marker is not None: r[MARKER] = marker
    return r


@pytest.mark.parametrize('marker', [None, True, '1', 0, 2])
def test_only_exact_new_marker_changes_initialization_reasoning(marker):
    r = current(marker); options = research_model_options('plan_workflow_init', {})
    result = options_for_record(r, 'plan_workflow_init', options)
    assert result['thinking'] == {'type': 'enabled'} and result['reasoning_effort'] == 'low'
    assert result['max_tokens'] == 6144 and result['timeout_seconds'] == 90


def test_direct_initializer_preserves_schema_cap_and_other_roles():
    old = current(None); new = current(); options = research_model_options('plan_workflow_init', {})
    before = options_for_record(old, 'plan_workflow_init', options)
    after = options_for_record(new, 'plan_workflow_init', options)
    assert after == {**before, 'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none'}
    for node in ('plan_workflow_meta', 'repair_workflow_meta', 'plan_experiment', 'verify', 'synthesize'):
        options = research_model_options(node, {})
        assert options_for_record(old, node, options) == options_for_record(new, node, options)


def test_current_marker_does_not_enable_direct_initialization_for_legacy_workflow():
    r = current(); r['executionWorkflowContractVersion'] = 6
    options = options_for_record(r, 'plan_workflow_init', research_model_options('plan_workflow_init', {}))
    assert options['reasoning_effort'] == 'low'


def test_complete_units_and_resume_keep_authored_initializers():
    from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
    from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
    from test_deep_research_workflow_metadata_repair import setup_repair, response
    initializers = explicit_initializers()
    r, _, invoke, run = setup_repair([response(scope_authored()), *map(response, initializers)])
    r.update(workflowMetadataRepairContractVersion=16, workflowInitializationOutputContractVersion=1)
    saved = run(); assert saved['status'] == 'ready' and not saved['scientificApproval']
    authored_responses = []
    for key, unit in saved['units'].items():
        if key == 'metadata': continue
        options = unit['request']['extra']
        assert options['thinking'] == {'type': 'disabled'} and options['reasoning_effort'] == 'none'
        assert options['max_tokens'] == 6144 and options['timeout_seconds'] == 90
        authored_responses.append(unit['response'])
    assert authored_responses == list(map(response, initializers))
    before = deepcopy(saved); calls = invoke.call_count
    assert run() == before and invoke.call_count == calls == 4


@pytest.mark.parametrize('replacement', [None, True, 2])
def test_marker_cannot_change_or_be_added_to_old_run(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'mark.sqlite3'); repo.initialize()
    repo.create_run(current()); before = repo.require_run('r')
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run('r', lambda r: {**r, MARKER: replacement})
    assert repo.require_run('r') == before
    old = current(None); old['runId'] = 'old'; old['idempotencyKey'] = 'old'; repo.create_run(old)
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run('old', lambda r: {**r, MARKER: 1})


@pytest.mark.parametrize('marker', [None, 1])
@pytest.mark.parametrize('scenario', ['success', 'unknown', 'token_budget', 'call_budget'])
def test_physical_send_reservation_and_unknown_deduplication(tmp_path, monkeypatch, marker, scenario):
    r = current(marker)
    if scenario == 'token_budget': r['budget']['maxTokens'] = 1
    if scenario == 'call_budget': r['budget'].update(modelCalls=13, reservedModelCalls=5)
    repo = DeepResearchRepository(tmp_path/'wire.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    raw = json.dumps(fixtures()[2][0], ensure_ascii=False)
    post = Mock(side_effect=requests.ReadTimeout('fixture')) if scenario == 'unknown' else Mock(return_value=http_response(raw))
    monkeypatch.setattr('llm.client.requests.post', post)
    provider = DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')
    scoped = ScopedModelClient(repo, lambda *a: True, lambda: provider).for_run('r')
    invoke = TrackedLLMInvoker(scoped, repo.reserve_call, repo.complete_call,
                              request_options=research_model_options, run_record_fn=repo.require_run,
                              experiment_max_input_bytes=32000)
    def run(prompt='Complete explicit initialization input'):
        return invoke('r', 'plan_workflow_init', prompt, {})
    if scenario in ('token_budget', 'call_budget'):
        for _ in range(2):
            with pytest.raises(BudgetExhaustedError): run()
        post.assert_not_called(); return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises(UnknownCallError): run()
        with pytest.raises(UnresolvedUnknownError): run('Changed')
    else:
        result = run(); assert run() == result and result['rawContent'] == raw
    assert post.call_count == 1
    wire = post.call_args.kwargs['json']
    assert wire['reasoning']['effort'] == ('none' if marker == 1 else 'low')
    assert wire['max_output_tokens'] == 6144
    assert wire['text']['format']['name'] == 'workflow_unit_init_v7'
    call = repo.list_calls('r')[0]
    assert call['reservedTokens'] == len('Complete explicit initialization input'.encode()) + 1024 + overhead_bytes(r, 'plan_workflow_init') + 6144
