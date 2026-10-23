"""Pinned source identities survive changed questions and adapter restarts."""
from urllib.parse import parse_qs, urlsplit

import pytest

from services.deep_research.external import AcademicAcquisition
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import ExternalAcademicAdapter
from services.deep_research_academic import AcademicPolicy, AcademicSourceClient


def atom(identities):
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(
        '<entry><id>https://arxiv.org/abs/' + value + '</id><title>Public method</title>'
        '<summary>Training uses supervised image reconstruction.</summary></entry>'
        for value in identities) + '</feed>').encode()


@pytest.fixture
def setup(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't', 'exactDiscoveryContractVersion': 1,
                     'sourcePolicy': {'mode': 'academic_external'}})
    repo.begin_execution('r')
    return repo


@pytest.mark.parametrize('identity', ['2308.04079v1', 'astro-ph/0612345v2'])
def test_pinned_paper_survives_two_different_reading_questions_and_repo_restart(setup, identity):
    repo = setup
    sends = []
    def transport(host, path, max_bytes):
        sends.append((host, parse_qs(urlsplit(path).query), max_bytes))
        return 'application/atom+xml', atom([identity])
    policy = AcademicPolicy(enabled=True, mode='academic_external')
    for question in ['解释训练信号', '核查失效条件']:
        repo = DeepResearchRepository(repo.db_path)
        repo.initialize()
        client = AcademicSourceClient(policy, transport)
        sources = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda _: client)(
            'r', [{'obligationId': 'o', 'query': question, 'question': question,
                   'requiredSources': ['arxiv:' + identity]}])
        assert sources[0]['versionId'] == 'arxiv:' + identity
        assert sources[0]['location'] == {'section': '摘要', 'offset': 0}
        assert sources[0]['accessLevel'] == 'abstract'
    assert len(sends) == len(repo.list_calls('r')) == 1
    assert sends[0][0] == 'export.arxiv.org'
    assert sends[0][1] == {'start': ['0'], 'max_results': ['3'], 'id_list': [identity]}
    assert repo.require_run('r')['budget']['externalSearches'] == 1


def test_exact_lookup_reuses_identical_settled_legacy_query_request(setup):
    sends = []
    def transport(*args):
        sends.append(args)
        return 'application/atom+xml', atom(['2308.04079v1'])
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'), transport)
    adapter = ExternalAcademicAdapter(client, setup.reserve_call, setup.complete_call)
    original = adapter.discover('r', '2308.04079v1 training', 3)
    assert adapter.lookup('r', ['2308.04079v1'], 3) == original
    assert len(sends) == len(setup.list_calls('r')) == 1


def test_multiple_papers_and_exact_versions_are_not_replaced_by_unrelated_results(setup):
    ids = ['2308.04079v1', 'astro-ph/0612345v2']
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'),
        lambda *_: ('application/atom+xml', atom([*ids, '2308.04079v3', '2311.17245v6'])))
    sources = AcademicAcquisition(setup, setup.complete_call, client_factory=lambda _: client)(
        'r', [{'obligationId': 'o', 'query': '比较训练', 'requiredSources': ['arxiv:' + i for i in ids]}])
    assert {source['versionId'] for source in sources} == {'arxiv:' + i for i in ids}


@pytest.mark.parametrize('identity', ['../../private', '2308.04079?token=x', 'https://arxiv.org/abs/2308.04079'])
def test_invalid_identity_never_reserves_or_sends(setup, identity):
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'),
                                  lambda *_: pytest.fail('No network'))
    adapter = ExternalAcademicAdapter(client, setup.reserve_call, setup.complete_call)
    with pytest.raises(ValueError):
        adapter.lookup('r', [identity], 3)
    assert not setup.list_calls('r')


def test_disabled_lookup_rejected_before_reservation(setup):
    client = AcademicSourceClient(AcademicPolicy(), lambda *_: pytest.fail('No network'))
    with pytest.raises(ValueError, match='未开启'):
        ExternalAcademicAdapter(client, setup.reserve_call, setup.complete_call).lookup('r', ['2308.04079'], 3)
    assert not setup.list_calls('r')


def test_exact_source_gap_only_fetches_requested_missing_version(setup):
    paths = []
    def transport(host, path, _):
        paths.append(parse_qs(urlsplit(path).query))
        return 'application/atom+xml', atom(['2308.04079v1'])
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'), transport)
    AcademicAcquisition(setup, setup.complete_call, client_factory=lambda _: client)(
        'r', [{'obligationId': 'o', 'query': '补查训练条件', 'missingSource': 'arxiv:2308.04079v1',
               'requiredSources': ['arxiv:2308.04079v1', 'arxiv:2311.17245v6']}])
    assert paths[0]['id_list'] == ['2308.04079v1']


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_server_freezes_exact_lookup_contract(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '研究方法',
            'exactDiscoveryContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['exactDiscoveryContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'exactDiscoveryContractVersion': replacement})
    finally:
        facade.shutdown()


def test_legacy_run_keeps_existing_request_identity(setup):
    setup.create_run({'runId': 'legacy', 'taskId': 't', 'sourcePolicy': {'mode': 'academic_external'}})
    setup.begin_execution('legacy')
    paths = []
    def transport(host, path, _):
        paths.append(parse_qs(urlsplit(path).query))
        return 'application/atom+xml', atom(['2308.04079v1'])
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'), transport)
    AcademicAcquisition(setup, setup.complete_call, client_factory=lambda _: client)(
        'legacy', [{'obligationId': 'o', 'query': 'training signal',
                    'requiredSources': ['arxiv:2308.04079v1']}])
    assert paths[0]['search_query'] == ['all:"training" AND all:"signal"']
    assert 'id_list' not in paths[0]


def test_wrong_version_is_not_read_as_the_pinned_version(setup):
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'),
        lambda *_: ('application/atom+xml', atom(['2308.04079v3'])))
    result = AcademicAcquisition(setup, setup.complete_call, client_factory=lambda _: client)(
        'r', [{'obligationId': 'o', 'query': '解释训练', 'requiredSources': ['arxiv:2308.04079v1']}])
    assert result == []
    assert len(setup.list_calls('r')) == 1
