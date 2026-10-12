import hashlib
from types import SimpleNamespace

import pytest

from services.deep_research.contracts import BudgetExhaustedError, RevisionConflictError, SettlementAlreadyError
from services.deep_research.external import AcademicAcquisition, capabilities, export_saved_source
from services.deep_research.publication import PublicationDispatcher
from services.deep_research.repository import DeepResearchRepository


@pytest.fixture
def repo(tmp_path):
    value = DeepResearchRepository(str(tmp_path / "research.sqlite3"))
    value.initialize()
    value.create_run({"runId": "r", "taskId": "t", "question": "public topic",
                      "sourcePolicy": {"mode": "academic_external"}})
    value.begin_execution("r")
    return value


class AcademicFixture:
    policy = SimpleNamespace(allow_fulltext=True)

    def __init__(self, *, fail=False):
        self.discoveries, self.fetches, self.fail = [], [], fail

    def discover(self, query, limit):
        self.discoveries.append(query)
        key = str(len(self.discoveries))
        return [{"workId": "arxiv:2601.0000" + key, "versionId": "arxiv:2601.0000" + key + "v1",
                 "arxivId": "2601.0000" + key + "v1", "title": "Public work " + key,
                 "url": "https://arxiv.org/abs/2601.0000" + key + "v1",
                 "abstract": "Abstract only reports a proposal.", "accessLevel": "abstract", "contentHash": "a" * 64}]

    def fetch_fulltext(self, arxiv_id):
        self.fetches.append(arxiv_id)
        if self.fail:
            raise OSError("offline")
        return {"accessLevel": "fulltext", "contentHash": "b" * 64,
                "pages": [{"page": 4, "text": "The public method reaches 95% accuracy on this fixed benchmark."}]}


def test_external_calls_are_separate_cached_and_literal_metadata_preserved(repo):
    fixture = AcademicFixture()
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda record: fixture)
    targets = [{"obligationId": "o", "query": "all:gaussian accuracy"}]
    sources = acquire("r", targets)
    again = acquire("r", targets)
    assert sources == again
    assert len(fixture.discoveries) == len(fixture.fetches) == 1
    assert sources[0]["accessLevel"] == "fulltext" and sources[0]["location"]["page"] == 4
    assert sources[0]["sourceKind"] == "arxiv" and sources[0]["obligationIds"] == ["o"]
    assert {call["tool"] for call in repo.list_calls("r")} == {"external_discover", "external_fulltext"}
    budget = repo.require_run("r")["budget"]
    assert budget["externalSearches"] == budget["fulltextFetches"] == 1


def test_unavailable_fulltext_remains_abstract_without_fabricated_page(repo):
    fixture = AcademicFixture(fail=True)
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda record: fixture)
    sources = acquire("r", [{"obligationId": "o", "query": "public topic"}])
    assert sources[0]["accessLevel"] == "abstract"
    assert "page" not in sources[0]["location"]
    assert repo.list_calls("r")[-1]["status"] == "failed"
    again = acquire("r", [{"obligationId": "o", "query": "public topic"}])
    assert again == sources and len(fixture.fetches) == 1


def test_one_external_work_can_support_multiple_obligations_without_refetch(repo):
    fixture = AcademicFixture()
    original_discover = fixture.discover
    fixture.discover = lambda query, limit: original_discover("same public topic", limit) if not fixture.discoveries else [{
        "workId": "arxiv:2601.00001", "versionId": "arxiv:2601.00001v1", "arxivId": "2601.00001v1"}]
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda record: fixture)
    sources = acquire("r", [{"obligationId": "o1", "query": "topic one"}, {"obligationId": "o2", "query": "topic two"}])
    assert sources and all(source["obligationIds"] == ["o1", "o2"] for source in sources)
    assert len(fixture.fetches) == 1


@pytest.mark.parametrize("key", ["maxExternalSearches", "maxFulltextFetches"])
def test_client_cannot_widen_network_budget(repo, key):
    record, _ = repo.create_run({"runId": key, "taskId": "t", "budget": {key: 1000}})
    assert record["budget"][key] == 6
    with pytest.raises(ValueError):
        repo.create_run({"runId": key + "-zero", "taskId": "t", "budget": {key: 0}})


def test_report_keeps_conditions_and_labels_in_summary_and_folds_evidence():
    from services.deep_research.reporting import conversation_summary, render_report
    claims = [{"claimId": "p", "kind": "proposal", "text": "固定四组对照", "evidenceRefs": ["e"],
               "conditions": {"数据": "同一训练测试划分"}},
              {"claimId": "long", "kind": "reported", "text": "x" * 600}]
    summary = conversation_summary(claims, "partial")
    assert "实验建议：" in summary and "同一训练测试划分" in summary and "证据缺口" in summary
    assert "xxx" not in summary
    body = render_report({"claims": claims[:1], "evidence": [{"evidenceId": "e", "quote": "original quote"}]})
    assert "<details>\n<summary>原文依据</summary>\n" in body
    assert "[1](#research-evidence-e)" in body


def test_task_only_policy_never_constructs_external_client(repo):
    repo.update_run("r", lambda r: {**r, "sourcePolicy": {"mode": "task_only"}})
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda record: pytest.fail("no external client"))
    assert acquire("r", [{"obligationId": "o", "query": "public"}]) == []
    assert not repo.list_calls("r")


@pytest.mark.parametrize("counter,limit", [("externalSearches", 6), ("fulltextFetches", 6)])
def test_network_limits_are_atomic_reservations(repo, counter, limit):
    for index in range(limit):
        repo.reserve_call(run_id="r", node="acquire", tool=counter, args_digest=str(index), budget_delta={counter: 1})
    with pytest.raises(BudgetExhaustedError):
        repo.reserve_call(run_id="r", node="acquire", tool=counter, args_digest="excess", budget_delta={counter: 1})
    assert repo.require_run("r")["budget"][counter] == limit


def test_zero_delta_settlement_cannot_replace_known_result(repo):
    call, _ = repo.reserve_call(run_id="r", node="acquire", tool="read", args_digest="zero", budget_delta={})
    repo.complete_call(call["callId"], status="succeeded", result={"stable": True})
    with pytest.raises(SettlementAlreadyError):
        repo.complete_call(call["callId"], status="failed", result={"stable": False})
    assert repo.list_calls("r")[0]["result"] == {"stable": True}


def test_resume_revision_is_checked_inside_execution_transaction(repo):
    paused = repo.transition("r", "paused")
    repo.update_run("r", lambda r: {**r, "stage": "updated"})
    with pytest.raises(RevisionConflictError):
        repo.begin_execution("r", expected_revision=paused["runRevision"])
    assert repo.require_run("r")["status"] == "paused"


def test_export_uses_saved_hash_and_never_fetches(repo, tmp_path, monkeypatch):
    body = b"%PDF-offline-existing-file"
    content_hash = hashlib.sha256(body).hexdigest()
    monkeypatch.setenv("DEEP_RESEARCH_SOURCE_DIR", str(tmp_path))
    (tmp_path / (content_hash + ".pdf")).write_bytes(body)
    source = {"sourceId": "s", "sourceKind": "arxiv", "workId": "arxiv:2601.00001",
              "arxivId": "2601.00001v1", "versionId": "arxiv:2601.00001v1", "contentHash": content_hash,
              "accessLevel": "fulltext", "title": "Existing paper"}
    repo.update_run("r", lambda r: {**r, "state": {"sources": [source]}})
    assert export_saved_source(repo, "r", "s")["pdfBase64"]
    (tmp_path / (content_hash + ".pdf")).write_bytes(b"changed")
    assert "pdfBase64" not in export_saved_source(repo, "r", "s")
    assert not repo.list_calls("r")


def test_outbox_delivery_replays_saved_publication_and_requires_matching_ack(repo):
    repo.publish_report(run_id="r", dedup_key="v1", payload={"reportVersionId": "v1"},
                        report_text="verified report", outcome="complete")
    requests = []
    def post(url, **kwargs):
        requests.append(url)
        version = "wrong" if len(requests) == 1 else "v1"
        return SimpleNamespace(status_code=200, json=lambda: {"status": "success", "runId": "r", "reportVersionId": version})
    publisher = PublicationDispatcher(repo, origin="http://127.0.0.1:8080/api", post=post)
    assert publisher.deliver_once() == 0
    assert publisher.deliver_once() == 1
    assert publisher.deliver_once() == 0
    assert len(requests) == 2 and not repo.list_calls("r")
    assert repo.require_run("r")["state"]["reportVersionId"] == "v1"


def test_capability_flags_do_not_silently_enable_external(monkeypatch):
    for key in ("DEEP_RESEARCH_V2_ENABLED", "DEEP_RESEARCH_EXTERNAL_ENABLED", "DEEP_RESEARCH_FULLTEXT_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    assert capabilities()["externalAcademic"] is False
    monkeypatch.setenv("DEEP_RESEARCH_V2_ENABLED", "true")
    assert capabilities()["externalAcademic"] is False
    monkeypatch.setenv("DEEP_RESEARCH_EXTERNAL_ENABLED", "true")
    assert capabilities()["externalAcademic"] is True and capabilities()["fulltext"] is False
