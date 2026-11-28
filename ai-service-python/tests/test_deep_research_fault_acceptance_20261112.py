"""H6 operational scenarios: synthetic HTTP, persistent SQLite, no live providers.

The fixture identifiers/titles below are never assertions about real papers.
Freeze this file's digest with the H6 definition before its first execution.
"""
from copy import deepcopy

import pytest

from services import deep_research_academic as academic
from services.deep_research.external import AcademicAcquisition
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph, make_acquire_node
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_end_to_end import FixtureModel


ATOM = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2601.99999v1</id><title>OFFLINE FIXTURE ONLY</title>
<summary>Offline fixture abstract describes a proposal, not measured results.</summary>
</entry></feed>'''


@pytest.mark.parametrize('fault', ['discovery_503', 'oversized_pdf', 'search_budget', 'private_dns', 'redirect'])
def test_h6_retains_acquired_abstract_then_stops_and_reopens_without_resend(tmp_path, monkeypatch, fault):
    requests, constructors, resolutions, reads = [], [], [], []

    class Response:
        def __init__(self, status, body=b'', content_type='application/atom+xml', length=None):
            self.status, self.body, self.content_type, self.length = status, body, content_type, length
        def getheader(self, name, default=None):
            return {'Content-Type': self.content_type, 'Content-Length': self.length,
                    'Location': 'http://127.0.0.1/forbidden'}.get(name, default)
        def read(self, size): reads.append(size); return self.body[:size]

    class Connection:
        def __init__(self, host, **kwargs): constructors.append(host)
        def request(self, method, path, **kwargs):
            assert method == 'GET'
            self.path = path; requests.append(path)
        def getresponse(self):
            if 'fixture_first' in self.path: return Response(200, ATOM)
            if self.path.startswith('/pdf/'):
                assert fault == 'oversized_pdf'
                return Response(200, b'%PDF-' + b'x' * 513, 'application/pdf', '518')
            assert 'fixture_second' in self.path
            return Response(301 if fault == 'redirect' else 503)
        def close(self): pass

    monkeypatch.setattr(academic.http.client, 'HTTPSConnection', Connection)

    def transport(host, path, maximum):
        def resolver(name):
            resolutions.append((name, path))
            return ['127.0.0.1'] if fault == 'private_dns' and 'fixture_second' in path else ['8.8.8.8']
        return academic.pinned_https_get(host, path, maximum, resolver=resolver)

    client = academic.AcademicSourceClient(academic.AcademicPolicy(
        enabled=True, mode='academic_external', allow_fulltext=fault == 'oversized_pdf',
        max_pdf_bytes=512), transport, cache_dir=None)
    client._parse_fulltext = lambda *_: pytest.fail('Oversized bytes must be refused before parser dispatch')
    repo = DeepResearchRepository(tmp_path / 'research.sqlite3'); repo.initialize()
    model = FixtureModel()
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=model,
                            retriever=lambda *a, **kw: pytest.fail('No local material is available'))
    try:
        record, _ = facade.create({
            'workspaceTaskId': 'offline-h6-' + fault, 'operationKey': 'one-submission',
            'question': 'Summarize the fixture proposal only when evidence is sufficient.',
            'sourcePolicy': {'mode': 'academic_external'}, 'deferStart': True,
            'materialSnapshot': {'materialRefs': [], 'materialVersions': [], 'snapshotHash': 'empty-h6'},
        }, start_async=False)
        rid = record['runId']
        targets = [{'obligationId': 'first', 'question': 'fixture proposal', 'searchQuery': 'all:fixture_first'}]
        if fault != 'oversized_pdf':
            targets.append({'obligationId': 'second', 'question': 'second proposal', 'searchQuery': 'all:fixture_second'})
        repo.update_run(rid, lambda r: {**r,
            'budget': {**r['budget'], 'maxExternalSearches': 1 if fault == 'search_budget' else 6},
            'state': {**r.get('state', {}), 'plan': [{'itemId': 'one', 'obligations': targets}]}})
        repo.begin_execution(rid)

        def acquire():
            external = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda _: client)
            node = make_acquire_node(lambda *a, **kw: pytest.fail('No local retrieval'),
                                     lambda *a: True, repo.update_run, external_acquire=external)
            return node({'run_id': rid})

        acquire()
        sources = deepcopy(repo.require_run(rid)['state']['sources'])
        assert len(sources) == 1 and sources[0]['accessLevel'] == 'abstract'
        assert sources[0]['location']['section'] == '摘要'
        assert sources[0]['text'] == 'Offline fixture abstract describes a proposal, not measured results.'
        assert sources[0]['versionId'] == 'arxiv:2601.99999v1'
        expected_requests = 1 if fault in {'private_dns', 'search_budget'} else 2
        assert len(requests) == len(constructors) == expected_requests
        assert len(reads) == 1  # No failed/redirect/oversized response body is consumed.
        calls = repo.list_calls(rid)
        expected_calls = 1 if fault == 'search_budget' else 2
        assert len(calls) == expected_calls
        assert calls[0]['status'] == 'succeeded'
        if fault != 'search_budget': assert calls[1]['status'] == 'failed'
        if fault == 'search_budget': assert repo.require_run(rid)['budget']['externalSearches'] == 1
        # Rebuilding acquisition reuses durable success/failure identities; no
        # HTTP resend, parser work, or new reservations for prior failures.
        acquire()
        assert len(requests) == expected_requests and len(repo.list_calls(rid)) == expected_calls
        assert repo.require_run(rid)['state']['sources'] == sources

        # Exercise the actual graph's budget-stop/publication path, not just
        # source persistence. One fixture brief is affordable; planning is not.
        # This is a server-side narrowed budget in an isolated run only.
        repo.update_run(rid, lambda r: {**r, 'budget': {**r['budget'],
            'maxModelCalls': 4, 'reserveModelCalls': 3}})
        facade._external_acquire = lambda *a: pytest.fail('Budget stop must prevent more acquisition')
        facade._execute_graph(rid)
        saved = repo.require_run(rid)
        assert saved['status'] == 'completed' and saved['outcome'] == 'inconclusive'
        assert len(model.requests) == 1 and len(requests) == expected_requests
        assert saved['state']['sources'] == sources
        assert not any(c['status'] in {'pending', 'unknown'} for c in repo.list_calls(rid))
        result = facade.get(rid)
        assert '尚未形成通过核验的结论' in result['report']['body']
        assert '95%' not in result['report']['body']
        if fault != 'oversized_pdf':
            assert all(c['tool'] != 'external_fulltext' for c in repo.list_calls(rid))

        facade.shutdown()
        reopened = DeepResearchRepository(repo.db_path); reopened.initialize(); reopened.recover()
        restored = ResearchFacade(reopened, lambda **kw: pytest.fail('GET must not construct graph'),
                                  llm_client=model, external_acquire=lambda *a: pytest.fail('GET cannot fetch'))
        try:
            before = deepcopy(reopened.require_run(rid)); ledger = deepcopy(reopened.list_calls(rid))
            assert restored.get(rid)['report'] == result['report']
            assert restored.get(rid)['outcome'] == 'inconclusive'
            assert reopened.require_run(rid) == before and reopened.list_calls(rid) == ledger
            assert before['state']['sources'] == sources
            assert len(model.requests) == 1 and len(requests) == expected_requests
        finally:
            restored.shutdown()
    finally:
        facade.shutdown()
