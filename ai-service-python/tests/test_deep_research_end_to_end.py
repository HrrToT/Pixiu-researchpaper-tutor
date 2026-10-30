"""Offline product flow with the real graph, repository, ledger and verifier.

Only the language model and local retrieval corpus are fixtures.
"""
import hashlib
import json
import re
import threading
import pytest
from dataclasses import replace
from unittest.mock import Mock, patch

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
                                  "requiredSources": ["alpha", "beta"], "completionCriteria": [
                                      {"criterionId": "results", "requirement": "State both papers' reported accuracy", "responseType": "identification"},
                                      {"criterionId": "conditions", "requirement": "State evaluation conditions and comparability", "responseType": "limitation"}]}]}]
        elif prompt.startswith("Extract evidence"):
            quote = next(text.split(". ")[0] + "." for text in PAPERS.values() if text in prompt)
            content = [{"quote": quote, "obligationIds": ["o"], "location": {"page": 3}}]
        elif prompt.startswith("For each evidence-obligation pair"):
            pairs = json.loads(prompt.split("Pairs:\n", 1)[1].split("\n\nReturn ", 1)[0])
            content = [{"pairId": pair["pairId"], "relevant": True}
                       for pair in pairs]
        elif prompt.startswith('Assess JOINT EVIDENCE READINESS'):
            units=json.JSONDecoder().raw_decode(prompt.split('Frozen units (questions, NOT facts):\n',1)[1])[0]
            # Both source premises and fixed-split context are available here;
            # readiness never approves bad99% or fills omitted final conditions.
            content=[{'unitId':u['unitId'],'ready':True,'evidenceIds':u['evidenceIds']} for u in units]
        elif prompt.startswith(("Synthesize", "Answer the exact research question")):
            ids = re.findall(r'"evidenceId":\s*"(E\d+)"', prompt)
            content = {"summary": "UNVERIFIED SUMMARY MUST NEVER BE SHOWN", "claims": [
                {"claimId": "c1", "text": "Alpha reports 95% accuracy.", "kind": "reported", "evidenceRefs": [ids[0]], "obligationIds": ["o"]},
                {"claimId": "c2", "text": "Beta reports 90% accuracy.", "kind": "reported", "evidenceRefs": [ids[1]], "obligationIds": ["o"]},
                {"claimId": "bad", "text": "Beta reports 99% accuracy.", "kind": "reported", "evidenceRefs": [ids[1]], "obligationIds": ["o"]}],
                "proposals": ["UNCHECKED PROPOSAL MUST NEVER BE SHOWN"], "gaps": []}
        elif prompt.startswith(("Verify these claims", "Check the complete factual assertions")):
            single_decision = prompt.startswith("Check the complete factual assertions")
            claims = json.loads(prompt.split('Claims:\n', 1)[1].split('\n\nEvidence:', 1)[0])
            content = [{"claimId": c['claimId'], "status": "passed"} for c in claims]
            if 'Scope-strength audit' in prompt:
                packet=json.JSONDecoder().raw_decode(prompt.split('Evidence:\n',1)[1])[0]
                for verdict,c in zip(content,claims):
                    ref=c['evidenceRefs'][0]
                    binding=({'statementPath':['text']} if 'For these targets bind the WHOLE assertion' in prompt
                             else {'statementExcerpt':c['text']})
                    verdict['scopeAudit']={'claimStrength':'bounded','evidenceStrength':'bounded',
                        'supported':True,**binding,
                        'premises':[{'evidenceId':ref,**({'path':['quote']}
                            if 'use ONLY unchanged source-field paths' in prompt
                            else {'quote':packet['evidence'][ref]['quote']})}]}
            if single_decision:
                for verdict in content:
                    verdict.pop('status')
                    verdict['reason']='The fixture source explicitly reports this value.'
        elif prompt.startswith(("Revise only the targets","Rebuild ONLY these rejected factual answer targets")):
            content = []  # An unsupported claim may be dropped; do not relax checks.
        elif prompt.startswith('Audit the FINAL ACCEPTED ANSWER against the FIXED REQUEST CHECKLIST'):
            required=json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
            content=[{'obligationId':o['obligationId'],'checks':[
                {'checkId':c['checkId'],'status':'partial',
                 'bindings':[{'claimId':'c1','field':'text'}],
                 'reason':'The fixture reports numerical results but omits requested evaluation conditions.'}
                for c in o['checks']]} for o in required]
        elif prompt.startswith("Audit whether the FINAL ACCEPTED ANSWER"):
            obligations = json.loads(prompt.split('Research and answer obligations (including the original question): ', 1)[1].split('\nAccepted final claims:', 1)[0])
            # Fixture claims retain numerical results but omit the requested
            # evaluation conditions. A factual pass is not a complete answer.
            content = [{'obligationId': o['obligationId'], 'status': 'partial',
                        'bindings': [{'claimId': 'c1', 'excerpt': 'Alpha reports 95% accuracy.'}]} for o in obligations]
        else:
            raise AssertionError("Unexpected model node: " + prompt[:80])
        if 'Also append EXACTLY ONE additional array row:' in prompt:
            content.append({'auditType':'answer_coherence','coherent':True,'issues':[]})
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
        published = repo.require_run(record["runId"])["result"]
        known = {e['evidenceId'] for e in published['evidence']}
        assert all(ref in known and ref.startswith('ev_') for c in published['claims'] for ref in c['evidenceRefs'])
        assert {source["pdfId"] for source in result["sources"]} == set(PAPERS)
        assert all(source["quote"] and source["page"] == 3 for source in result["sources"])
        calls = repo.list_calls(record["runId"])
        assert sum(c["tool"] == "llm_invoke" for c in calls) == len(model.requests) == 10
        assert sum(c['node'] == 'verify' for c in calls) == 2
        assert sum(c['node'] == 'verify_answer_coverage' for c in calls) == 1
        assert result['outcome'] == 'partial'
        assert any(g.get('stage') == 'answer' for g in published['gaps'])
        assert all(c["status"] == "succeeded" for c in calls)
        assert result["budget"]["tokens"] == 2000
        assert len(repo.list_outbox(record["runId"])) == 1
        calls_before = len(model.requests)
        restored = DeepResearchRepository(repo.db_path)
        restored.recover()
        assert restored.require_run(record["runId"])["status"] == "completed"
        assert facade.get(record["runId"])["report"]["body"] == body
        assert len(model.requests) == calls_before
    finally:
        facade.shutdown()


def test_truncated_verification_fails_without_publishing_evidence_insufficiency(tmp_path):
    class TruncatedVerifier(FixtureModel):
        def invoke(self, request):
            if request.prompt.startswith(('Verify these claims','Check the complete factual assertions')):
                self.requests.append(request)
                return LLMResult('fixture', 'fixture-v1', '', LLMUsage(120, 8192, 8312),
                                 finish_reason='length')
            return super().invoke(request)

    model = TruncatedVerifier()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        rid = record['runId']
        repo.begin_execution(rid)
        facade._execute_graph(rid)
        result = facade.get(rid)
        assert result['status'] == 'failed'
        assert result['errorCode'] == 'invalid_verification_response'
        assert '结论核验未完成' in result['error']
        assert '这不表示论文证据不足' in result['error']
        assert '查看已保存的结果' not in result['error']
        assert not repo.list_outbox(rid)
        saved = repo.require_run(rid)
        assert saved['state']['evidence'] and saved['state']['reportBody']
        calls = [c for c in repo.list_calls(rid) if c['node'] == 'verify']
        assert len(calls) == 1 and calls[0]['status'] == 'succeeded'
        assert sum(r.prompt.startswith(('Verify these claims','Check the complete factual assertions')) for r in model.requests) == 1
    finally:
        facade.shutdown()


def test_absolute_provider_timeout_preserves_unknown_and_ignores_late_response(tmp_path):
    from llm.client import DeepSeekLLM
    release, closed = threading.Event(), threading.Event()
    response = Mock()
    response.close.side_effect = closed.set

    def transport(*args, **kwargs):
        # Only the provider's absolute 30ms deadline should expire. Logging and
        # durable controller bookkeeping may take longer under filesystem load;
        # the fixture must keep the late response alive until explicit release.
        assert release.wait(30)
        return response

    class TimedVerifier(FixtureModel):
        def invoke(self, request):
            if request.prompt.startswith(('Verify these claims','Check the complete factual assertions')):
                self.requests.append(request)
                return DeepSeekLLM(api_key='fixture', base_url='https://example.invalid').invoke(
                    replace(request, timeout_seconds=0.03))
            return super().invoke(request)

    model = TimedVerifier()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        rid = record['runId']
        repo.begin_execution(rid)
        with patch('llm.client.requests.post', side_effect=transport) as post:
            facade._execute_graph(rid)
            assert repo.require_run(rid)['status'] == 'paused'
            assert repo.require_run(rid)['errorCode'] == 'unresolved_unknown'
            calls = [c for c in repo.list_calls(rid) if c['node'] == 'verify']
            assert len(calls) == 1 and calls[0]['status'] == 'unknown'
            assert calls[0]['reservedTokens'] > 0
            before = repo.require_run(rid)['budget'].copy()
            release.set()
            assert closed.wait(5)
            assert repo.require_run(rid)['budget'] == before
            assert not repo.list_outbox(rid)
            assert [c for c in repo.list_calls(rid) if c['node'] == 'verify'][0]['status'] == 'unknown'
            post.assert_called_once()
    finally:
        release.set()
        facade.shutdown()


@pytest.mark.parametrize('prefix,node', [
    ('Analyze this research question', 'resolve_brief'),
    ('Audit the FINAL ACCEPTED ANSWER against the FIXED REQUEST CHECKLIST', 'verify_answer_coverage'),
    ('Rebuild ONLY these rejected factual answer targets', 'repair_claims'),
])
def test_pause_keeps_known_inflight_response_and_resume_does_not_resend_it(tmp_path, prefix, node):
    entered, release = threading.Event(), threading.Event()

    class PausingModel(FixtureModel):
        def invoke(self, request):
            if request.prompt.startswith(prefix):
                entered.set()
                assert release.wait(5)
            return super().invoke(request)

    model = PausingModel()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        facade._start_execution(record["runId"])
        assert entered.wait(10)
        current = repo.require_run(record["runId"])
        worker = facade._active_futures[record["runId"]]
        facade.action(record["runId"], "pause", {"requestId": "pause", "expectedRunRevision": current["runRevision"]})
        release.set()
        worker.result(timeout=5)
        assert repo.require_run(record["runId"])["status"] == "paused"
        assert sum(r.prompt.startswith(prefix) for r in model.requests) == 1
        assert [c for c in repo.list_calls(record['runId']) if c['node'] == node][0]['status'] == 'succeeded'
        paused = repo.require_run(record["runId"])
        facade.action(record["runId"], "resume", {"requestId": "resume", "expectedRunRevision": paused["runRevision"]})
        with facade._lock:
            next_worker = facade._active_futures.get(record["runId"])
        if next_worker:
            next_worker.result(timeout=30)  # Allow the complete offline resumed graph to finish.
        assert repo.require_run(record["runId"])["status"] == "completed"
        assert sum(r.prompt.startswith(prefix) for r in model.requests) == 1
    finally:
        release.set()
        facade.shutdown()


def test_actual_budget_stop_publishes_inconclusive_without_more_model_calls(tmp_path):
    model = FixtureModel()
    repo, facade, _ = make_facade(tmp_path, model)
    try:
        record = create(facade)
        repo.update_run(record["runId"], lambda r: {**r, "budget": {**r["budget"], "maxModelCalls": 4, "reserveModelCalls": 3}})
        repo.begin_execution(record["runId"])
        facade._execute_graph(record["runId"])
        result = facade.get(record["runId"])
        assert result["status"] == "completed" and result["outcome"] == "inconclusive"
        assert len(model.requests) == 1
        assert "尚未形成通过核验的结论" in result["report"]["body"]
        assert "论文事实已按" not in result["report"]["body"]
        assert repo.require_run(record['runId'])['result']['limitations'] == ''
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
