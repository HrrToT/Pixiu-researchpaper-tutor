import json
from unittest.mock import Mock

import pytest

from core.config import settings
from llm.openai_research import OpenAIResearchLLM
from llm.provider import LLMProviderError, LLMRequest
from services.deep_research.external import AcademicAcquisition
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.runtime import ScopedModelClient


def client(api_key="test-key"):
    return OpenAIResearchLLM(model="gpt-5.4-mini", api_key=api_key, timeout_seconds=12)


def mock_response(monkeypatch, status, body):
    response = Mock(status_code=status, headers={"x-request-id": "req_test"})
    response.json.return_value = body
    post = Mock(return_value=response)
    monkeypatch.setattr("llm.client.requests.post", post)
    return post


@pytest.mark.parametrize('count', [5000, None])
def test_comparison_fact_review_counts_only_after_byte_reservation_fails(tmp_path, monkeypatch, count):
    from services.deep_research.contracts import BudgetExhaustedError
    from services.deep_research.factual_review import OPTION as BOUNDED_REVIEW_OPTION
    from services.deep_research.tools import TrackedLLMInvoker

    monkeypatch.setattr(settings, 'openai_api_key', 'test-key')
    repo = DeepResearchRepository(tmp_path / 'research.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, Mock(), llm_client=Mock(), openai_research_models=('main', 'routine'),
                            comparison_cells_version=1)
    try:
        created, _ = facade.create({'workspaceTaskId': 'task', 'operationKey': 'op',
                                    'question': 'Compare the two papers.', 'outputKind': 'paper_comparison'},
                                   start_async=False)
        run_id = created['runId']
        assert created['countedComparisonFactReviewContractVersion'] == 1
        repo.begin_execution(run_id)
        repo.update_run(run_id, lambda row: {**row, 'budget': {
            **row['budget'], 'modelCalls': 12, 'reservedModelCalls': 5,
            'tokens': 82692, 'normalTokens': 52352,
        }, 'state': {**row['state'], 'outputKind': 'paper_comparison'}})
        scope = Mock()
        scope.validate_run.return_value = True
        provider = ScopedModelClient(repo, scope, Mock()).for_run(run_id)
        invoke = TrackedLLMInvoker(provider, repo.reserve_call, repo.complete_call,
                                  run_record_fn=repo.require_run, call_history_fn=repo.list_calls)
        posts = []

        def post(url, **kwargs):
            posts.append(kwargs['json'])
            if url.endswith('/input_tokens'):
                assert not repo.list_calls(run_id)
                response = Mock(status_code=200 if count is not None else 503)
                response.json.return_value = {'object': 'response.input_tokens', 'input_tokens': count}
                return response
            (reserved,) = repo.list_calls(run_id)
            assert reserved['status'] == 'pending' and reserved['reservedTokens'] == count + 9216
            response = Mock(status_code=200, headers={})
            response.json.return_value = {
                'status': 'completed',
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"items":[]}'}]}],
                'usage': {'input_tokens': count, 'output_tokens': 20, 'total_tokens': count + 20},
            }
            return response

        monkeypatch.setattr('llm.client.requests.post', post)
        prompt = 'Evaluate the frozen comparison evidence. ' + 'x' * 17500
        options = {BOUNDED_REVIEW_OPTION: True, 'max_tokens': 4000}
        if count is None:
            with pytest.raises(BudgetExhaustedError):
                invoke(run_id, 'verify', prompt, options, use_reserve=True)
            assert len(posts) == 1 and not repo.list_calls(run_id)
        else:
            result = invoke(run_id, 'verify', prompt, options, use_reserve=True)
            assert result['auditInputTokens'] == count
            measured, generated = posts
            assert measured == {k: v for k, v in generated.items() if k not in {'store', 'max_output_tokens'}}
            assert invoke(run_id, 'verify', prompt, options, use_reserve=True) == result
            assert len(posts) == 2 and repo.require_run(run_id)['budget']['tokens'] == 82692 + count + 20
    finally:
        facade.shutdown()


def test_chat_request_is_bounded_and_reports_actual_usage(monkeypatch):
    post = mock_response(monkeypatch, 200, {
        "model": "gpt-5.4-mini-2026-03-17",
        "choices": [{"message": {"content": '{"answer":"yes"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
                  "prompt_tokens_details": {"cached_tokens": 7, "cache_write_tokens": 3}},
    })
    result = client().invoke(LLMRequest(prompt="Return a JSON object", timeout_seconds=3, extra_body={
        "thinking": {"type": "disabled"}, "reasoning_effort": "high",
        "max_tokens": 80, "response_format": {"type": "json_object"}, "temperature": 0.2,
    }))
    args, kwargs = post.call_args
    assert args == ("https://api.openai.com/v1/chat/completions",)
    assert kwargs["timeout"] == 3 and kwargs["allow_redirects"] is False
    assert kwargs["json"] == {
        "model": "gpt-5.4-mini", "messages": [{"role": "user", "content": "Return a JSON object"}],
        "reasoning_effort": "none", "max_completion_tokens": 80,
        "response_format": {"type": "json_object"}, "store": False,
    }
    assert result.provider == "openai"
    assert result.finish_reason == "stop" and result.reported_model == "gpt-5.4-mini-2026-03-17"
    assert (result.usage.total_tokens, result.usage.estimated) == (17, False)
    assert (result.usage.cached_input_tokens, result.usage.cache_write_input_tokens) == (7, 3)


def test_responses_preserves_schema_observation_and_token_limit(monkeypatch):
    post = mock_response(monkeypatch, 200, {
        "status": "completed", "output": [{"type": "reasoning"}, {
            "type": "message", "content": [{"type": "output_text", "text": "{}"}],
        }],
        "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 5}},
    })
    schema = {"type": "object", "properties": {"optional": {"type": "string"}}}
    result = client().invoke(LLMRequest(prompt="Return JSON", extra_body={
        "_deepseek_api": "responses", "_deepseek_observe_headers": True,
        "max_tokens": 120, "reasoning_effort": "max",
        "response_format": {"type": "json_schema", "name": "example", "schema": schema},
    }))
    args, kwargs = post.call_args
    assert args == ("https://api.openai.com/v1/responses",)
    assert kwargs["stream"] is True  # Observe HTTP headers before reading JSON.
    assert kwargs["json"] == {
        "model": "gpt-5.4-mini", "input": [{"role": "user", "content": "Return JSON"}],
        "max_output_tokens": 120, "reasoning": {"effort": "high"},
        "text": {"format": {"type": "json_schema", "name": "example", "schema": schema, "strict": False}},
        "store": False,
    }
    assert result.content == "{}" and result.usage.total_tokens == 13
    assert (result.usage.cached_input_tokens, result.usage.cache_write_input_tokens) == (0, 5)
    assert result.provider_observation["requestId"] == "req_test"


@pytest.mark.parametrize("details", [None, {"cached_tokens": True},
                                     {"cached_tokens": 7, "cache_write_tokens": 5}])
def test_absent_or_invalid_cache_usage_keeps_reported_totals(monkeypatch, details):
    mock_response(monkeypatch, 200, {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13,
                  "prompt_tokens_details": details},
    })
    usage = client().invoke(LLMRequest(prompt="research")).usage
    assert usage.total_tokens == 13 and not usage.estimated
    assert usage.cached_input_tokens is None and usage.cache_write_input_tokens is None


@pytest.mark.parametrize(("code", "status", "retryable"), [
    ("credit_balance_exhausted", 402, False),
    ("rate_limit_exceeded", 429, True),
])
def test_quota_failure_is_distinct_from_rate_limiting(monkeypatch, code, status, retryable):
    post = mock_response(monkeypatch, 429, {"error": {"code": code}})
    with pytest.raises(LLMProviderError) as error:
        client().invoke(LLMRequest(prompt="Return JSON"))
    assert error.value.status_code == status and error.value.retryable is retryable
    post.assert_called_once()


def test_existing_runs_stay_on_original_provider_and_new_models_are_pinned(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    post = mock_response(monkeypatch, 200, {"choices": [{"message": {"content": "ok"}}]})
    repo = Mock()
    record = {"budget": {"maxWallClockSeconds": 30}, "materials": []}
    repo.require_run.return_value = record
    legacy_provider = Mock()
    bound = ScopedModelClient(repo, lambda *_: True, lambda: legacy_provider).for_run("run")
    request = LLMRequest(prompt="research")
    bound.invoke(request)
    legacy_provider.invoke.assert_called_once()
    post.assert_not_called()
    record["openaiResearchModels"] = ["pinned-main", "pinned-routine"]
    bound.for_node("verify").invoke(request)
    assert post.call_args.kwargs["json"]["model"] == "pinned-main"
    bound.for_node("extract").invoke(request)
    assert post.call_args.kwargs["json"]["model"] == "pinned-routine"
    legacy_provider.invoke.assert_called_once()


def test_provider_snapshot_is_server_owned_and_replayed_after_config_change(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / "research.sqlite3"))
    repo.initialize()
    request = {"workspaceTaskId": "task", "operationKey": "op", "question": "Compare",
               "deferStart": True, "openaiResearchModels": ["client-model"]}
    with_openai = ResearchFacade(repo, Mock(), llm_client=Mock(), openai_research_models=("main", "routine"))
    without_openai = ResearchFacade(repo, Mock(), llm_client=Mock())
    try:
        record, created = with_openai.create(request, start_async=False)
        assert created and record["openaiResearchModels"] == ["main", "routine"]
        duplicate, created = without_openai.create(request, start_async=False)
        assert not created and duplicate["openaiResearchModels"] == ["main", "routine"]
        with pytest.raises(ValueError, match="Immutable run field changed: openaiResearchModels"):
            repo.update_run(record["runId"], lambda run: {**run, "openaiResearchModels": ["different", "routine"]})
    finally:
        with_openai.shutdown(wait=True)
        without_openai.shutdown(wait=True)


def test_openai_run_does_not_dispatch_deepseek_search(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / "research.sqlite3"))
    repo.initialize()
    repo.create_run({"runId": "r", "taskId": "t", "question": "public topic",
                     "sourcePolicy": {"mode": "academic_external"}, "openaiResearchModels": ["main", "routine"]})
    repo.begin_execution("r")
    academic = Mock()
    academic.discover.return_value = []
    deepseek_search = Mock()
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda _: academic,
                                  fallback_search=deepseek_search)
    assert acquire("r", [{"obligationId": "topic", "query": "public topic"}]) == []
    academic.discover.assert_called_once()
    deepseek_search.assert_not_called()


@pytest.mark.parametrize("count, expected_failure, no_call_slots", [
    (8923, None, False), (23000, "budget_exhausted", False), (True, "budget_exhausted", False),
    (None, "budget_exhausted", False), (8923, "scope_revoked", False),
    (8923, "budget_exhausted", True),
])
def test_counted_comparison_audit_uses_the_same_context_and_reserves_before_generation(
        tmp_path, monkeypatch, count, expected_failure, no_call_slots):
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.tools import TrackedLLMInvoker
    from test_deep_research_comparison_audit_envelope import value

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    repo = DeepResearchRepository(tmp_path / "research.sqlite3")
    repo.initialize()
    facade = ResearchFacade(repo, Mock(), llm_client=Mock(), openai_research_models=("main", "routine"),
                            comparison_cells_version=1)
    try:
        created, _ = facade.create({"workspaceTaskId": "task", "operationKey": "op", "question": "Compare",
                                    "outputKind": "paper_comparison"}, start_async=False)
        run_id = created["runId"]
        assert created["countedComparisonAuditContractVersion"] == 1
        with pytest.raises(ValueError, match="Immutable run field changed: countedComparisonAuditContractVersion"):
            repo.update_run(run_id, lambda row: {**row, "countedComparisonAuditContractVersion": 0})
        repo.begin_execution(run_id)
        repo.update_run(run_id, lambda row: {
            **row, "budget": {**row["budget"], "tokens": 79730, "normalTokens": 49000,
                             **({"modelCalls": 13, "reservedModelCalls": 5} if no_call_slots else {})},
            "state": {**row["state"], "outputKind": "paper_comparison"},
        })
        scope = Mock()
        scope.validate_run.return_value = expected_failure != "scope_revoked"
        bound = ScopedModelClient(repo, scope, Mock()).for_run(run_id)
        invoke = TrackedLLMInvoker(bound, repo.reserve_call, repo.complete_call,
                                  run_record_fn=repo.require_run, call_history_fn=repo.list_calls,
                                  verification_max_input_bytes=32000)
        calls = []
        def post(url, **kwargs):
            calls.append((url, kwargs["json"]))
            assert kwargs["allow_redirects"] is False
            if url.endswith("/input_tokens"):
                assert not repo.list_calls(run_id)
                response = Mock(status_code=503 if count is None else 200)
                response.json.return_value = {"object": "response.input_tokens", "input_tokens": count}
                return response
            assert url == "https://api.openai.com/v1/responses"
            (reserved,) = repo.list_calls(run_id)
            assert reserved["status"] == "pending"
            assert reserved["reservedTokens"] == count + 1024 + 3500
            response = Mock(status_code=200, headers={})
            response.json.return_value = {
                "status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps(value())},
                ]}], "usage": {"input_tokens": count, "output_tokens": 80, "total_tokens": count + 80},
            }
            return response
        monkeypatch.setattr("llm.client.requests.post", post)
        options = {"max_tokens": 3500, "temperature": 0.0}
        prompt = "Review the frozen JSON audit inputs. " + "x" * 33000
        assert created["comparisonAuditEnvelopeContractVersion"] == 21
        with pytest.raises(ValueError, match="exceeds max 32000 bytes"):
            invoke(run_id, "verify_answer_coverage", prompt, options, use_reserve=True)
        with pytest.raises(ValueError, match="exceeds max 36000 bytes"):
            invoke(run_id, "verify_answer_coverage", prompt + "x" * 3000, options,
                   use_reserve=True, counted_audit=True)
        assert not calls and not repo.list_calls(run_id)

        def send():
            return invoke(run_id, "verify_answer_coverage", prompt, options, use_reserve=True, counted_audit=True)

        if expected_failure:
            with pytest.raises(DeepResearchError) as error:
                send()
            assert error.value.code == expected_failure
            assert len(calls) == (0 if expected_failure == "scope_revoked" or no_call_slots else 1)
            if no_call_slots:
                assert error.value.details == {"kind": "modelCalls", "limit": 18, "used": 18}
            assert not repo.list_calls(run_id)
            return

        result = send()
        assert result["auditInputTokens"] == count and result["usage"]["total_tokens"] == count + 80
        assert result["structuredOutput"]["receivedShape"] == "comparison_audit_v1"
        assert repo.require_run(run_id)["budget"]["tokens"] == 79730 + count + 80
        assert send() == result and len(calls) == 2
        (_, measured), (_, generated) = calls
        assert measured == {key: val for key, val in generated.items() if key not in {"store", "max_output_tokens"}}
        assert generated["input"][-1]["content"] == prompt
    finally:
        facade.shutdown()


@pytest.mark.parametrize("tokens,count,ordinary_calls,window_version,expected_sends", [
    (20000, 8900, None, 0, ["/responses"]),
    (79000, 8900, None, 0, ["/responses/input_tokens", "/responses"]),
    (79000, 24000, None, 0, ["/responses/input_tokens"]),
    (79000, 8900, 7, 0, ["/responses/input_tokens", "/responses"]),
    (79000, 8900, 13, 0, []),
    (20000, 9300, None, 1, ["/responses/input_tokens", "/responses"]),
    (20000, None, None, 1, ["/responses/input_tokens"]),
    (92000, 9300, None, 1, ["/responses/input_tokens"]),
    (98000, 9300, None, 1, []),
    (20000, 9800, None, 2, []),
    (20000, 9800, None, 3, ["/responses/input_tokens", "/responses"]),
    (92000, 9800, None, 3, ["/responses/input_tokens"]),
    (20000, 9800, None, 4, ["/responses/input_tokens", "/responses"]),
])
def test_scientific_review_counts_when_required_for_admission(
        tmp_path, monkeypatch, tokens, count, ordinary_calls, window_version, expected_sends):
    assert_experiment_input_count(
        tmp_path, monkeypatch, tokens, count, ordinary_calls, window_version, expected_sends,
    )


def assert_experiment_input_count(
        tmp_path, monkeypatch, tokens, count, ordinary_calls, window_version, expected_sends,
        repair_audit_version=0):
    from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
    from services.deep_research.planning_transport import overhead_bytes
    from services.deep_research.shared_experiment_review import CHECK_IDS_OPTION, NODE
    from services.deep_research.tools import TrackedLLMInvoker
    from test_deep_research_shared_experiment_review import ready

    record, _, _ = ready()
    record.update(openaiResearchModels=["main", "routine"], countedExperimentReviewContractVersion=1)
    node = "repair_experiment_shared" if repair_audit_version else NODE
    if repair_audit_version:
        record["sharedExperimentFinalAuditPacketVersion"] = repair_audit_version
    if window_version:
        record.update(countedExperimentReviewWindowVersion=window_version, sharedExperimentScopedReviewPacketVersion=7,
                      sharedExperimentReviewReferenceVersion=4)
    record["budget"].update(tokens=tokens, maxTokens=100000, normalTokens=0)
    if ordinary_calls is not None:
        record["budget"].update(modelCalls=ordinary_calls, reservedModelCalls=5, reserveModelCalls=5,
                                reserveTokens=50000, normalTokens=26078, finalizationBudgetVersion=1)
    repo = DeepResearchRepository(tmp_path / "science.sqlite3")
    repo.initialize()
    assert repo.create_run(record)[1]
    repo.begin_execution(record["runId"])
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    bound = ScopedModelClient(repo, lambda *_: True, Mock()).for_run(record["runId"])
    invoker = TrackedLLMInvoker(bound, repo.reserve_call, repo.complete_call, run_record_fn=repo.require_run,
                                call_history_fn=repo.list_calls, verification_max_input_bytes=32000,
                                experiment_max_input_bytes=32000 if window_version or repair_audit_version else None)
    sends = []
    def post(url, **kwargs):
        path = url.removeprefix("https://api.openai.com/v1")
        sends.append((path, kwargs["json"]))
        response = Mock(status_code=200, headers={})
        if path.endswith("/input_tokens"):
            assert not repo.list_calls(record["runId"])
            response.json.return_value = {"object": "response.input_tokens", "input_tokens": count}
        else:
            (reserved,) = repo.list_calls(record["runId"])
            assert reserved["status"] == "pending"
            if len(expected_sends) == 2:
                assert reserved["reservedTokens"] == count + 1024 + 4096
            response.json.return_value = {"status":"completed","output":[{"type":"message","content":[
                {"type":"output_text","text":"{}"},
            ]}],"usage":{"input_tokens":count,"output_tokens":10,"total_tokens":count+10}}
        return response

    monkeypatch.setattr("llm.client.requests.post", post)
    def send():
        options = {"max_tokens": 4096}
        if window_version:
            options[CHECK_IDS_OPTION] = ["section_0"]
        size = {0: 24000, 1: 33000, 2: 35500, 3: 35500, 4: 35500}[window_version]
        if repair_audit_version:
            size = 30330
        prompt = "Check the JSON proposal. "
        padding = size - overhead_bytes(repo.require_run(record["runId"]), node, options) - len(prompt)
        return invoker(record["runId"], node, prompt + "x" * padding,
                       options, use_reserve=True)
    if window_version == 2:
        with pytest.raises(ValueError, match="exceeds max 35000 bytes"):
            send()
        assert not repo.list_calls(record["runId"])
    elif count is None:
        with pytest.raises(DeepResearchError) as failure:
            send()
        assert failure.value.code == "shared_experiment_review_count_unavailable"
        assert not repo.list_calls(record["runId"])
    elif not expected_sends or expected_sends[-1].endswith("/input_tokens"):
        with pytest.raises(BudgetExhaustedError):
            send()
        assert not repo.list_calls(record["runId"])
    else:
        result = send()
        assert result.get("auditInputTokens") == (count if len(expected_sends) == 2 else None)
        assert send() == result
    assert [path for path, _ in sends] == expected_sends
    if len(sends) == 2:
        measured, generated = (payload for _, payload in sends)
        assert measured == {k:v for k,v in generated.items() if k not in {"store", "max_output_tokens"}}
        assert measured["text"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize('version,count,calls,sends', [
    (1, 8900, 6, []),
    (2, 8900, 6, ['/responses/input_tokens', '/responses']),
    (2, 22000, 6, ['/responses/input_tokens']),
    (2, 8900, 13, []),
])
def test_experiment_repair_counts_only_for_the_new_profile(tmp_path, monkeypatch, version, count, calls, sends):
    assert_experiment_input_count(
        tmp_path, monkeypatch, 77043, count, calls, 0, sends, repair_audit_version=version,
    )
