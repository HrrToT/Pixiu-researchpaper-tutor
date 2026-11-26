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
