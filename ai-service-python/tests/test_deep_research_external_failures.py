"""Equivalent arXiv lookups must not multiply sends or hide provider failures."""
import json

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.contracts import DeepResearchError
from services.deep_research.external import AcademicAcquisition
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph, make_acquire_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import ExternalAcademicAdapter
from services.deep_research_academic import AcademicPolicy, AcademicSourceClient


@pytest.fixture
def repo(tmp_path):
    value = DeepResearchRepository(str(tmp_path / 'research.sqlite3'))
    value.initialize()
    return value


def begin(repo):
    repo.create_run({'runId': 'r', 'taskId': 't', 'question': 'public topic',
                     'sourcePolicy': {'mode': 'academic_external'}})
    repo.begin_execution('r')


@pytest.mark.parametrize('failed', [False, True])
def test_equivalent_requests_reuse_durable_result_even_after_adapter_recreation(repo, failed):
    begin(repo)
    sends = []
    def transport(*args):
        sends.append(args)
        if failed:
            raise OSError('fixture unavailable')
        return 'application/atom+xml', b'<feed xmlns="http://www.w3.org/2005/Atom" />'
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'), transport)
    for query in ['2310.08528v3 encoder', 'decoder arXiv:2310.08528v3', '2310.08528v3 metadata']:
        adapter = ExternalAcademicAdapter(client, repo.reserve_call, repo.complete_call)
        assert adapter.discover('r', query, 3) == []
        assert adapter.discovery_outcomes == ['failed' if failed else 'succeeded']
    assert len(sends) == len(repo.list_calls('r')) == 1
    assert repo.require_run('r')['budget']['externalSearches'] == 1
    # Versions and limits are distinct actual requests, not overbroad query caching.
    adapter.discover('r', '2310.08528v2 encoder', 3)
    adapter.discover('r', '2310.08528v3 encoder', 2)
    assert len(sends) == 3


def test_disabled_client_rejects_before_call_reservation(repo):
    begin(repo)
    client = AcademicSourceClient(AcademicPolicy(), lambda *a: pytest.fail('no send'))
    adapter = ExternalAcademicAdapter(client, repo.reserve_call, repo.complete_call)
    with pytest.raises(ValueError, match='未开启'):
        adapter.discover('r', '2310.08528v3')
    assert repo.list_calls('r') == []


def test_empty_successful_search_is_not_provider_failure(repo):
    begin(repo)
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'),
        lambda *a: ('application/atom+xml', b'<feed xmlns="http://www.w3.org/2005/Atom" />'))
    acquire = AcademicAcquisition(repo, repo.complete_call, client_factory=lambda _: client)
    assert acquire('r', [{'obligationId': 'o', 'query': '2310.08528v3'}]) == []


def test_local_sources_survive_external_supplement_failure(repo):
    begin(repo)
    local = {'sourceId': 'local', 'workId': 'paper', 'text': 'Existing evidence.', 'obligationIds': ['o']}
    repo.update_run('r', lambda r: {**r, 'state': {'sources': [local], 'plan': []}})
    def external(*args):
        raise DeepResearchError('external_discovery_unavailable', 'fixture')
    node = make_acquire_node(lambda *a, **kw: [], lambda *a: True, repo.update_run,
                             external_acquire=external)
    node({'run_id': 'r'})
    assert repo.require_run('r')['state']['sources'] == [local]


def test_real_graph_exposes_acquisition_failure_without_synthesis_or_publication(repo):
    nodes, sends = [], []
    class Model:
        def invoke(self, request):
            if request.prompt.startswith('Analyze this research question'):
                nodes.append('brief')
                content = {'outputKind': 'direction_survey', 'clarification': ''}
            elif request.prompt.startswith('Create a research plan'):
                nodes.append('plan')
                content = [{'itemId': 'i', 'question': 'Explain encoder and decoder', 'dependencies': [],
                    'obligations': [{'obligationId': 'o1', 'question': 'encoder',
                        'searchQuery': '2310.08528v3 encoder', 'requiredSources': []},
                        {'obligationId': 'o2', 'question': 'decoder',
                         'searchQuery': '2310.08528v3 decoder', 'requiredSources': []}]}]
            else:
                pytest.fail('Must not generate an answer after acquisition failure: ' + request.prompt[:80])
            return LLMResult('fixture', 'fixture', json.dumps(content), LLMUsage(10, 10, 20))
    def transport(*args):
        sends.append(args)
        raise OSError('fixture outage')
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external'), transport)
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=Model(),
                             scope_validator=lambda *a: True)
    facade._external_acquire = AcademicAcquisition(repo, facade._complete_tracked_call,
                                                   client_factory=lambda _: client)
    try:
        record = facade.create({'workspaceTaskId': 't', 'operationKey': 'once',
            'question': 'Explain the encoder and decoder in arXiv:2310.08528v3.', 'deferStart': True,
            'sourcePolicy': {'mode': 'academic_external'},
            'materialSnapshot': {'materialRefs': [], 'materialVersions': [], 'snapshotHash': 'empty'}},
            start_async=False)[0]
        rid = record['runId']
        repo.begin_execution(rid)
        facade._execute_graph(rid)
        result = facade.get(rid)
        assert result['status'] == 'failed'
        assert result['errorCode'] == 'external_discovery_unavailable'
        assert '尚未读到所需资料' in result['error']
        assert '这不表示论文缺少证据' in result['error']
        assert nodes == ['brief', 'plan']
        assert len(sends) == 1
        assert not repo.list_outbox(rid)
        # Viewing/recovering a terminal run must not retry the failed request.
        repo.recover()
        assert facade.get(rid)['status'] == 'failed'
        assert len(sends) == 1
    finally:
        facade.shutdown()
