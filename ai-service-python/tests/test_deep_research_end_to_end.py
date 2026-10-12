"""Offline product flow with the real graph, repository, ledger and verifier.

Only the language model and local retrieval corpus are fixtures.
"""
import hashlib
import json
import re
import threading

from llm.provider import LLMResult, LLMUsage
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository


PAPERS = {
    "alpha": "Alpha reports 95% accuracy on the fixed benchmark. The evaluation uses the same held out split for all methods.",
    "beta": "Beta reports 90% accuracy on the fixed benchmark. The evaluation uses the same held out split for all methods.",
}


class FixtureModel:
    def __init__(self):
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        prompt = request.prompt
        if prompt.startswith("Analyze this research question"):
            content = {"outputKind": "paper_comparison", "clarification": ""}
        elif prompt.startswith("Create a research plan"):
            content = [{"itemId": "i", "question": "比较同一评测条件下的结果", "dependencies": [],
                "obligations": [{"obligationId": "o", "question": "accuracy fixed benchmark",
                                  "requiredSources": ["alpha", "beta"]}]}]
        elif prompt.startswith("Extract evidence"):
            quote = next(text.split(". ")[0] + "." for text in PAPERS.values() if text in prompt)
            content = [{"quote": quote, "obligationIds": ["o"], "location": {"page": 3}}]
        elif prompt.startswith("For each evidence-obligation pair"):
            pairs = json.loads(prompt.split("Pairs:\n", 1)[1].split("\n\nReturn ", 1)[0])
            content = [{"evidenceId": pair["evidenceId"], "obligationId": pair["obligationId"], "relevant": True}
                       for pair in pairs]
        elif prompt.startswith("Synthesize"):
            ids = re.findall(r'"evidenceId":\s*"(ev_[^"]+)"', prompt)
            content = {"summary": "UNVERIFIED SUMMARY MUST NEVER BE SHOWN", "claims": [
                {"claimId": "c1", "text": "Alpha reports 95% accuracy.", "kind": "reported", "evidenceRefs": [ids[0]]},
                {"claimId": "c2", "text": "Beta reports 90% accuracy.", "kind": "reported", "evidenceRefs": [ids[1]]},
                {"claimId": "bad", "text": "Beta reports 99% accuracy.", "kind": "reported", "evidenceRefs": [ids[1]]}],
                "proposals": ["UNCHECKED PROPOSAL MUST NEVER BE SHOWN"], "gaps": []}
        elif prompt.startswith("Verify these claims"):
            content = [{"claimId": "c1", "status": "passed"}, {"claimId": "c2", "status": "passed"}]
        else:
            raise AssertionError("Unexpected model node: " + prompt[:80])
        return LLMResult("fixture", "fixture-v1", json.dumps(content), LLMUsage(120, 80, 200))


def make_facade(tmp_path, model):
    repo = DeepResearchRepository(str(tmp_path / "research.sqlite3"))
    repo.initialize()
    retrieved = []

    def retrieve(query, pdf_id, *, limit=5):
        retrieved.append((query, pdf_id))
        return [{"sourceId": f"{pdf_id}-chunk-1", "pdfId": pdf_id, "text": PAPERS[pdf_id],
                 "location": {"page": 3, "chunk": 1}, "accessLevel": "fulltext"}]

    # Source IDs are deliberately NOT material IDs: the graph must map owners.
    def validate(rid, material_id):
        return material_id in PAPERS

    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=model,
                            retriever=retrieve, scope_validator=validate)
    return repo, facade, retrieved


def create(facade):
    return facade.create({"workspaceTaskId": "workspace", "operationKey": "op",
        "question": "比较论文报告的准确率及条件，不使用外部来源。", "deferStart": True,
        "materialSnapshot": {"materialRefs": list(PAPERS), "snapshotHash": "snapshot-v1",
            "materialVersions": [{"id": key, "contentHash": hashlib.sha256(value.encode()).hexdigest()}
                                 for key, value in PAPERS.items()]}}, start_async=False)[0]


def test_real_graph_publishes_only_verified_body_and_reopens_without_generation(tmp_path):
    model = FixtureModel()
    repo, facade, retrieved = make_facade(tmp_path, model)
    try:
        record = create(facade)
        repo.begin_execution(record["runId"])
        facade._execute_graph(record["runId"])
        result = facade.get(record["runId"])
        assert result["status"] == "completed", repo.require_run(record["runId"])
        body = result["report"]["body"]
        assert isinstance(body, str) and "95%" in body and "90%" in body
        assert "99%" not in body and "UNVERIFIED" not in body and "UNCHECKED" not in body
        assert {paper for _, paper in retrieved} == set(PAPERS)
        assert len(repo.require_run(record["runId"])["state"]["evidence"]) == 2
        assert {source["pdfId"] for source in result["sources"]} == set(PAPERS)
        assert all(source["quote"] and source["page"] == 3 for source in result["sources"])
        calls = repo.list_calls(record["runId"])
        assert sum(c["tool"] == "llm_invoke" for c in calls) == len(model.requests) == 7
        assert all(c["status"] == "succeeded" for c in calls)
        assert result["budget"]["tokens"] == 1400
        assert len(repo.list_outbox(record["runId"])) == 1
        calls_before = len(model.requests)
        restored = DeepResearchRepository(repo.db_path)
        restored.recover()
        assert restored.require_run(record["runId"])["status"] == "completed"
        assert facade.get(record["runId"])["report"]["body"] == body
        assert len(model.requests) == calls_before
    finally:
        facade.shutdown()


def test_pause_keeps_known_inflight_response_and_resume_does_not_resend_it(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class PausingModel(FixtureModel):
        def invoke(self, request):
            if not self.requests:
                entered.set()
                assert release.wait(5)
            return super().invoke(request)

    model = PausingModel()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        facade._start_execution(record["runId"])
        assert entered.wait(3)
        current = repo.require_run(record["runId"])
        worker = facade._active_futures[record["runId"]]
        facade.action(record["runId"], "pause", {"requestId": "pause", "expectedRunRevision": current["runRevision"]})
        release.set()
        worker.result(timeout=5)
        assert repo.require_run(record["runId"])["status"] == "paused"
        assert len(model.requests) == 1
        assert repo.list_calls(record["runId"])[0]["status"] == "succeeded"
        paused = repo.require_run(record["runId"])
        facade.action(record["runId"], "resume", {"requestId": "resume", "expectedRunRevision": paused["runRevision"]})
        with facade._lock:
            next_worker = facade._active_futures.get(record["runId"])
        if next_worker:
            next_worker.result(timeout=5)
        assert repo.require_run(record["runId"])["status"] == "completed"
        assert sum(r.prompt.startswith("Analyze this research question") for r in model.requests) == 1
    finally:
        release.set()
        facade.shutdown()


def test_actual_budget_stop_publishes_inconclusive_without_more_model_calls(tmp_path):
    model = FixtureModel()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        repo.update_run(record["runId"], lambda r: {**r, "budget": {**r["budget"], "maxModelCalls": 4}})
        repo.begin_execution(record["runId"])
        facade._execute_graph(record["runId"])
        result = facade.get(record["runId"])
        assert result["status"] == "completed" and result["outcome"] == "inconclusive"
        assert len(model.requests) == 1
        assert "证据不足" in result["report"]["body"]
    finally:
        facade.shutdown()


def test_unknown_submission_pauses_and_does_not_send_following_nodes(tmp_path):
    from llm.provider import LLMProviderError
    class UncertainModel:
        calls = 0
        def invoke(self, request):
            self.calls += 1
            raise LLMProviderError("timeout", provider="fixture", model="fixture", retryable=True)
    model = UncertainModel()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        repo.begin_execution(record["runId"])
        facade._execute_graph(record["runId"])
        result = facade.get(record["runId"])
        assert result["status"] == "paused" and result["errorCode"] == "unresolved_unknown"
        assert "resume" not in result["allowedActions"]
        assert model.calls == 1 and repo.list_calls(record["runId"])[0]["status"] == "unknown"
        assert facade.get(record["runId"])["report"] is None
        assert model.calls == 1
    finally:
        facade.shutdown()
