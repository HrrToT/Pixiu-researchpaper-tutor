"""Complete revisions remain bounded and cannot upgrade historical requests."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.workflow_revision_context import enabled, NODE
from services.deep_research.workflow_revision_input import input_limit
from services.deep_research.workflow_metadata_repair import prepare
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.planning_transport import overhead_bytes
from services.deep_research.experiment_planning import request_identity
from test_deep_research_workflow_metadata_planning_output import record as planning_record
from test_deep_research_workflow_revision_input import failed, sized_source, StopBeforeProvider


def previous():
    return {**planning_record(), 'workflowRevisionInputContractVersion': 1}


def record():
    return {**previous(), 'workflowRevisionContextContractVersion': 1}


@pytest.mark.parametrize('marker', [None, True, False, 0, 2, '1'])
def test_strict_marker_preserves_legacy_window(marker):
    r = {**record(), 'workflowRevisionContextContractVersion': marker}
    if type(marker) is int and marker == 2:
        assert enabled(r) and input_limit(r) == 64000
        return
    assert not enabled(r) and input_limit(r) == 40000


@pytest.mark.parametrize('key', ['workflowRevisionInputContractVersion',
    'workflowMetadataPlanningOutputContractVersion', 'workflowMetadataInputContractVersion',
    'workflowMetadataEnvelopeContractVersion', 'workflowMetadataRepairContractVersion'])
def test_incomplete_profile_cannot_activate(key):
    r = {**record(), key: 0}
    assert not enabled(r) and input_limit(r) <= 40000


@pytest.mark.parametrize('size,allowed', [(40001, True), (46775, True), (64000, True), (64001, False)])
def test_complete_revision_admission_preserves_entire_request(size, allowed):
    r = record(); w, unit = failed(); source, aliases = sized_source(r, w, size)
    saved = []; invoke = Mock(side_effect=StopBeforeProvider()); before = deepcopy(unit)
    with pytest.raises(StopBeforeProvider if allowed else DeepResearchError):
        prepare(r, source_data=source, failed=unit, aliases=aliases, existing=None,
                invoke=invoke, checkpoint=saved.append)
    assert unit == before and invoke.call_count == int(allowed)
    assert saved[-1]['status'] == ('pending' if allowed else 'not_started_capacity')
    assert saved[-1]['scientificApproval'] is False
    if not allowed: assert saved[-1]['maxInputBytes'] == 64000


def test_no_prompt_output_schema_or_deadline_change():
    assert request_identity(record(), NODE, 'complete original input', {}) == request_identity(previous(), NODE, 'complete original input', {})


def test_old_capacity_failure_cannot_be_reopened_with_new_marker():
    r = previous(); w, unit = failed(); source, aliases = sized_source(r, w, 46775)
    saved = []; invoke = Mock()
    with pytest.raises(DeepResearchError):
        prepare(r, source_data=source, failed=unit, aliases=aliases, existing=None, invoke=invoke, checkpoint=saved.append)
    assert saved[-1]['status'] == 'not_started_capacity'
    with pytest.raises(DeepResearchError, match='不一致'):
        prepare(record(), source_data=source, failed=unit, aliases=aliases, existing=saved[-1], invoke=invoke, checkpoint=saved.append)
    invoke.assert_not_called()


@pytest.mark.parametrize('cap', [32000, 40000, 64000])
def test_invoker_applies_configured_limit_and_whole_budget_before_http(cap):
    reserve = Mock(side_effect=BudgetExhaustedError('tokens', 100001, 100000)); client = Mock()
    invoke = TrackedLLMInvoker(client, reserve, Mock(), run_record_fn=lambda _: record(),
        experiment_max_input_bytes=32000, workflow_revision_max_input_bytes=40000,
        workflow_revision_context_max_input_bytes=cap)
    assert invoke.prompt_byte_limit('r', NODE) == cap
    for node in ('plan_workflow_meta', 'plan_workflow_init', 'plan_experiment_outline'):
        assert invoke.prompt_byte_limit('r', node) <= 40000
    n = cap - overhead_bytes(record(), NODE)
    with pytest.raises(BudgetExhaustedError): invoke('r', NODE, 'x' * n, {'max_tokens': 6144})
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == cap + 1024 + 6144
    with pytest.raises(ValueError, match='Prompt too large'): invoke('r', NODE, 'x' * (n + 1), {'max_tokens': 6144})
    assert reserve.call_count == 1
    client.invoke.assert_not_called()


@pytest.mark.parametrize('cap', [True, 0, 64001, '64000'])
def test_invalid_server_caps_rejected(cap):
    with pytest.raises(ValueError, match='workflow revision context'):
        TrackedLLMInvoker(Mock(), Mock(), Mock(), workflow_revision_context_max_input_bytes=cap)


def test_legacy_ignores_complete_context_configuration():
    invoke = TrackedLLMInvoker(Mock(), Mock(), Mock(), run_record_fn=lambda _: previous(),
        workflow_revision_max_input_bytes=40000, workflow_revision_context_max_input_bytes=64000)
    assert invoke.prompt_byte_limit('r', NODE) == 40000


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_sqlite_reservation_and_actual_http_keep_identity_and_no_resend(tmp_path, monkeypatch, scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.planning_transport import dispatch_options
    from services.deep_research.contracts import digest, UnknownCallError, UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r = record(); r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    post = Mock(side_effect=requests.ReadTimeout('unknown')) if scenario == 'unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post', post)
    client = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    reserve = Mock(side_effect=BudgetExhaustedError('tokens', 100001, 100000)) if scenario == 'budget' else Mock(wraps=repo.reserve_call)
    invoke = TrackedLLMInvoker(client, reserve, repo.complete_call, request_options=research_model_options,
        run_record_fn=repo.require_run, workflow_revision_max_input_bytes=40000, workflow_revision_context_max_input_bytes=64000)
    req = request_identity(r, NODE, 'x' * (46775 - overhead_bytes(r, NODE)), {})
    def run(): return invoke('r', NODE, req['prompt'], dispatch_options(r, NODE, req['extra']), use_reserve=True)
    if scenario == 'budget':
        with pytest.raises(BudgetExhaustedError): run()
        post.assert_not_called(); return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises((UnknownCallError, UnresolvedUnknownError)): run()
    else: run()
    assert post.call_count == 1 and repo.list_calls('r')[0]['argsDigest'] == digest(req)
    assert post.call_args.kwargs['json']['max_output_tokens'] == 6144
    assert post.call_args.kwargs['timeout'] == 90
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == 46775 + 1024 + 6144


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_server_owned_immutable_marker(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Design',
            'deferStart': True, 'workflowRevisionContextContractVersion': replacement}, start_async=False)
        assert r['workflowRevisionContextContractVersion'] == 3
        probe = deepcopy(r); probe['outputKind'] = 'experiment_design'
        assert enabled(probe)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda x: {**x, 'workflowRevisionContextContractVersion': replacement})
        old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop('workflowRevisionContextContractVersion'); repo.create_run(old)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run('old', lambda x: {**x, 'workflowRevisionContextContractVersion': 1})
    finally: facade.shutdown()
