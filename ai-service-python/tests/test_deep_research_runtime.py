from datetime import datetime, UTC, timedelta
from unittest.mock import Mock

import pytest

from llm.provider import LLMRequest
from services.deep_research.contracts import DeepResearchError
from services.deep_research.runtime import AuthoritativeScopeValidator, ScopedModelClient, read_acquired_source


def repo():
    value = Mock()
    value.require_run.return_value = {"taskId": "task/中文", "materials": [{"materialId": "p"}],
        "materialSnapshot": {"snapshotHash": "h"}, "budget": {"maxWallClockSeconds": 360},
        "startedAt": (datetime.now(UTC) - timedelta(seconds=350)).isoformat()}
    return value


def test_authoritative_scope_identity_readiness_and_no_redirect():
    store = repo()
    post = Mock()
    post.return_value = Mock(status_code=200, content=b"{}")
    post.return_value.json.return_value = {"valid": True, "snapshotValid": True,
        "taskId": "task/中文", "runId": "run"}
    validate = AuthoritativeScopeValidator(store, post=post)
    assert validate("run", "p")
    args, kwargs = post.call_args
    assert "task%2F%E4%B8%AD%E6%96%87" in args[0]
    assert kwargs == {"json": {"snapshotHash": "h"}, "timeout": 3, "allow_redirects": False}
    post.return_value.json.return_value["runId"] = "foreign"
    assert not validate("run", "p")
    post.return_value.status_code = 302
    assert not validate("run", "p")
    assert not validate("run", "foreign-paper")


def test_scope_failure_prevents_provider_send_and_deadline_caps_request():
    store = repo()
    provider = Mock()
    validate = Mock(return_value=False)
    client = ScopedModelClient(store, validate, lambda: provider).for_run("run")
    with pytest.raises(DeepResearchError, match="材料"):
        client.invoke(LLMRequest(prompt="answer", timeout_seconds=60))
    provider.invoke.assert_not_called()
    validate.return_value = True
    client.invoke(LLMRequest(prompt="answer", timeout_seconds=60))
    request = provider.invoke.call_args.args[0]
    assert 0 < request.timeout_seconds <= 10
    assert request.messages[0]["role"] == "system"
    assert request.extra_body["thinking"] == {"type": "disabled"}
    store.require_run.return_value["startedAt"] = (datetime.now(UTC) - timedelta(seconds=361)).isoformat()
    provider.reset_mock()
    with pytest.raises(DeepResearchError, match="预算"):
        client.invoke(LLMRequest(prompt="answer"))
    provider.invoke.assert_not_called()


def test_reader_returns_persisted_location_and_does_not_fetch():
    store = repo()
    store.require_run.return_value["state"] = {"sources": [{"sourceId": "s", "workId": "p",
        "text": "exact original", "versionId": "v", "contentHash": "h", "accessLevel": "fulltext",
        "location": {"page": 4, "chunk": 2}}]}
    result = read_acquired_source(store, "run", "s")
    assert result["pages"] == [{"text": "exact original", "page": 4, "chunk": 2}]
    assert result["contentHash"] == "h"
    with pytest.raises(DeepResearchError, match="未保存"):
        read_acquired_source(store, "run", "missing")


def test_routine_model_route_retains_scope_checks_and_complex_model():
    store, reasoning, routine = repo(), Mock(), Mock()
    validate = Mock(return_value=True)
    client = ScopedModelClient(store, validate, lambda: reasoning, lambda: routine).for_run("run")
    for node in ("resolve_brief", "extract", "assess_relevance"):
        client.for_node(node).invoke(LLMRequest(prompt="public evidence"))
    assert routine.invoke.call_count == 3
    reasoning.invoke.assert_not_called()
    client.for_node("synthesize").invoke(LLMRequest(prompt="reasoning"))
    assert reasoning.invoke.call_count == 1
    validate.return_value = False
    with pytest.raises(DeepResearchError):
        client.for_node("extract").invoke(LLMRequest(prompt="revoked"))
    assert routine.invoke.call_count == 3


def test_disabled_runtime_does_not_create_store(tmp_path, monkeypatch):
    from services.deep_research import runtime
    monkeypatch.setenv("DEEP_RESEARCH_V2_ENABLED", "false")
    target = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("DEEP_RESEARCH_DB_PATH", str(target))
    assert runtime.initialize_runtime() is None
    assert not target.exists()
