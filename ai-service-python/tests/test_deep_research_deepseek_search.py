from urllib.parse import parse_qs, urlsplit

import pytest

from services.deep_research import deepseek_search
from services.deep_research.contracts import DeepResearchError
from services.deep_research.external import AcademicAcquisition
from services.deep_research.repository import DeepResearchRepository
from services.deep_research_academic import AcademicAccessError, AcademicPolicy, AcademicSourceClient


PAPER = '2403.17888v3'


@pytest.mark.parametrize('mode, fulltext, pinned, results, pdf_available, expect_download', [
    ('external_only', True, True, ['2403.17888v1'], True, True),
    ('external_only', True, True, ['2403.17888v1'], False, True),
    ('external_only', True, False, ['2403.17888', PAPER], True, True),
    ('external_only', True, False, ['2403.17888'], True, False),
    ('external_only', True, False, [], True, False),
    ('external_only', False, False, [PAPER], True, False),
    ('task_only', True, False, [PAPER], True, False),
])
def test_fallback_uses_only_pinned_pdf_and_settled_attempts(tmp_path, monkeypatch, mode, fulltext,
                                                           pinned, results, pdf_available, expect_download):
    repo = DeepResearchRepository(tmp_path / 'research.sqlite3')
    repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't', 'exactDiscoveryContractVersion': 2,
                     'sourcePolicy': {'mode': mode}})
    repo.begin_execution('r')
    sends = []
    searches = []
    def transport(host, path, _):
        sends.append((host, path))
        if host == 'export.arxiv.org':
            raise AcademicAccessError('metadata unavailable')
        if not pdf_available:
            raise AcademicAccessError('pinned revision unavailable')
        return 'application/pdf', b'%PDF-fixture'

    def search(key, query, count):
        searches.append((query, count))
        return [{'url': f'https://arxiv.org.evil.invalid/abs/{PAPER}', 'title': 'wrong host'},
                *[{'url': f'https://arxiv.org/abs/{identity}', 'title': 'Public paper',
                   'snippet': 'UNVERIFIED_SEARCH_TEXT'} for identity in results]]

    monkeypatch.setattr(deepseek_search, 'read_search_results', search)
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode=mode, allow_fulltext=fulltext), transport)
    monkeypatch.setattr(client, '_parse_fulltext', lambda _: [{'page': 1, 'text': 'Fetched passage.'}])
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda _: client,
                                  fallback_search=deepseek_search.DeepSeekAcademicSearch('fixture-key'),
                                  direct_pinned_fallback=True)
    targets = [{'obligationId': 'o', 'query': 'public research topic', 'question': 'local brief',
                'requiredSources': ['arxiv:' + PAPER] if pinned else []}]
    for _ in range(2):
        if mode == 'external_only' and (not fulltext or pinned and not pdf_available):
            with pytest.raises(DeepResearchError, match='外部文献获取失败'):
                acquire('r', targets)
            continue
        sources = acquire('r', targets)
        assert [source['text'] for source in sources] == (
            ['Fetched passage.'] if expect_download and pdf_available else [])
        if sources:
            assert sources[0]['versionId'] == 'arxiv:' + PAPER
            assert sources[0]['location']['page'] == 1
            assert sources[0]['discoveryProvider'] == ('pinned_arxiv_pdf' if pinned else 'deepseek_search')

    if mode == 'task_only':
        assert sends == searches == repo.list_calls('r') == []
        return
    params = parse_qs(urlsplit(sends[0][1]).query)
    assert params.get('id_list') == ([PAPER] if pinned else None)
    assert [path for host, path in sends[1:] if host == 'arxiv.org'] == (
        ['/pdf/' + PAPER] if expect_download else [])
    assert len(sends) == 1 + int(expect_download)
    assert searches == ([('site:arxiv.org public research topic', 6)] if fulltext and not pinned else [])
    assert repo.require_run('r')['budget']['externalSearches'] == 1 + len(searches)


def test_provider_http_request_disables_redirects_and_content(monkeypatch):
    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def iter_content(self, _):
            yield b'{"results": []}'

    def post(url, **kwargs):
        assert url == 'https://api.deepseek.com/v1/tools/search'
        assert kwargs['headers'] == {'Authorization': 'Bearer fixture-key'}
        assert kwargs['json'] == {'query': 'site:arxiv.org paper', 'count': 6, 'need_content': False}
        assert kwargs['allow_redirects'] is False
        return Response()

    monkeypatch.setattr(deepseek_search.requests, 'post', post)
    assert deepseek_search.DeepSeekAcademicSearch('fixture-key')('paper', 6) == []
