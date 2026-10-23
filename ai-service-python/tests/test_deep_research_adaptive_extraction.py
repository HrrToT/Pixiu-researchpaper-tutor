import json
from copy import deepcopy

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.coverage import coverage_gaps, validate_plan
from services.deep_research.dependencies import initialize
from services.deep_research.extraction import make_batched_extract_node, _input_capacity
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence
from test_deep_research_extraction import setup


def activate(repo, **markers):
    old = repo.require_run('r')
    fresh = DeepResearchRepository(str(repo.db_path)+'.adaptive'); fresh.initialize()
    fresh.create_run({'runId': 'r', 'taskId': 't', 'state': old['state'],
        'adaptiveResearchContractVersion': 1, 'adaptiveExtractionContractVersion': 1, **markers})
    fresh.begin_execution('r')
    return fresh


@pytest.mark.parametrize('response,finish', [('[]', 'stop'), ('bad JSON', 'stop'), ('[]', 'length')])
def test_one_batch_returns_to_assessment_and_never_resends_reviewed_passages(tmp_path, response, finish):
    repo, reads = setup(tmp_path)
    repo = activate(repo)
    fourth = deepcopy(reads[-1]); fourth['sourceId'] = 'fourth'
    fourth['pages'][0]['text'] = 'The final paragraph states a distinct and relevant evaluation condition.'
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'readResults': [*reads, fourth]}})
    sends = []
    def invoke(_, node, prompt, options):
        values = json.loads(prompt.split('Passages:\n', 1)[1])
        sends.append([p['sourceId'] for p in values])
        return {'content': response, 'finishReason': finish}
    node = make_batched_extract_node(invoke, make_evidence, lambda *_: True, repo.update_run)
    assert node({'run_id': 'r'})['extraction_pending'] is True
    repo = DeepResearchRepository(repo.db_path); repo.initialize()
    node = make_batched_extract_node(invoke, make_evidence, lambda *_: True, repo.update_run)
    assert node({'run_id': 'r'})['extraction_pending'] is False
    assert sends == [['s0', 's1', 's2'], ['fourth']]
    node({'run_id': 'r'})
    assert len(sends) == 2


def test_large_batch_fits_whole_passages_without_borrowing_repair_budget(tmp_path):
    repo, reads = setup(tmp_path)
    repo = activate(repo)
    for row in reads:
        row['pages'][0]['text'] = ('A complete sentence records the relevant evaluation settings. ' * 60)[:3000]
    repo.update_run('r', lambda r: {**r, 'budget': {**r['budget'], 'normalTokens': 6500},
                                  'state': {**r['state'], 'readResults': reads}})
    sends = []
    def invoke(_, node, prompt, options):
        values = json.loads(prompt.split('Passages:\n', 1)[1]); sends.extend(values)
        assert len(prompt.encode('utf8')) <= _input_capacity(repo.require_run('r')['budget'])
        return {'content': '[]', 'finishReason': 'stop'}
    result = make_batched_extract_node(invoke, make_evidence, lambda *_: True, repo.update_run)({'run_id': 'r'})
    assert len(sends) == 1 and sends[0]['text'] == reads[0]['pages'][0]['text']
    assert result['extraction_pending'] is True
    assert repo.require_run('r')['budget']['normalTokens'] == 6500  # fixture did not settle real usage


@pytest.mark.parametrize('schedule', [0,1])
@pytest.mark.parametrize('overview_evidence', [False,True])
def test_compiled_graph_checks_unread_local_batch_before_requery(tmp_path,schedule,overview_evidence):
    repo, reads = setup(tmp_path)
    repo = activate(repo, dependencyContractVersion=1,extractionScheduleContractVersion=schedule)
    values = [{'itemId': 'i', 'question': 'Explain the evaluation condition', 'dependencies': [],
               'obligations': [{'obligationId': 'o', 'question': 'Explain the evaluation condition', 'requiredSources': ['p']}]}]
    repo.update_run('r', lambda r: {**r,
        'materials': [{'materialId': 'p', 'pdfId': 'p', 'versionId': 'v'}],
        'state': {**r['state'], 'plan': values, 'dependencyExecution': initialize(values), 'readResults': []}})
    texts = {f's{i}': ('Background sentence unrelated to the research request.' if i < 3
                      else 'The evaluation condition uses fixed cameras and a held-out image split.') for i in range(4)}
    if overview_evidence:
        texts['s0']='The input overview mentions an evaluation without specifying its camera condition.'
    retrieves = []; extracts = []; events=[]
    def retrieve(query, pdf_id, limit=5):
        retrieves.append(query)
        return [{'sourceId': sid, 'sourceWorkId': 'p', 'versionId': 'v', 'text': text,
                 'accessLevel': 'fulltext', 'location': {'page': i+1}} for i, (sid, text) in enumerate(texts.items())]
    def invoke(_, node, prompt, *args, **kwargs):
        if node == 'resolve_brief': result = {'outputKind': 'claim_verification', 'clarification': ''}
        elif node == 'plan': result = values
        elif node == 'extract':
            events.append('extract')
            passages = json.loads(prompt.split('Passages:\n', 1)[1])
            extracts.append([p['sourceId'] for p in passages])
            result = [{'sourceId': p['sourceId'], 'quote': p['text'], 'obligationIds': ['o'], 'conditions': {}}
                      for p in passages if 'fixed cameras' in p['text'] or 'input overview' in p['text']]
        elif node == 'assess_relevance':
            events.append('assess')
            pairs = json.loads(prompt.split('Pairs:\n', 1)[1].split('\n\nReturn', 1)[0])
            result = [{'pairId': p['pairId'], 'relevant': 'fixed cameras' in p['quote']} for p in pairs]
        elif node == 'synthesize': raise DeepResearchError('fixture_stop', 'Inspect routing only')
        else: pytest.fail(node)
        return {'content': json.dumps(result), 'finishReason': 'stop'}
    graph = build_deep_research_graph(llm_invoke=invoke, retrieve_fn=retrieve,
        read_fn=lambda rid, sid: {'accessLevel': 'fulltext', 'pages': [{'page': list(texts).index(sid)+1, 'text': texts[sid]}]},
        scope_validator=lambda *_: True, make_evidence_fn=make_evidence, coverage_gaps_fn=coverage_gaps,
        verify_claims_fn=lambda *_: {}, repo_update=repo.update_run, repo_publish=repo.publish_report,
        validate_plan_fn=validate_plan, extract_batch_size=3)
    with pytest.raises(DeepResearchError, match='routing only'):
        graph.invoke({'run_id': 'r', 'execution_epoch': 1})
    assert extracts == [['s0', 's1', 's2'], ['s3']] and len(retrieves) == 1
    # Empty extraction cannot pass readiness. The new scheduler reaches the
    # fourth operative paragraph before the independent assessment is sent.
    expected=(['extract','assess','extract','assess'] if overview_evidence and not schedule
              else ['extract','extract','assess'])
    assert events==expected
    assert repo.require_run('r')['state']['dependencyExecution']['requeryCount'] == 0
    assert not repo.require_run('r')['state']['gaps']


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_extraction_contract_is_immutable_and_server_owned(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '解释方法',
            'deferStart': True, 'adaptiveExtractionContractVersion': replacement}, start_async=False)
        assert run['adaptiveExtractionContractVersion'] == 2
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'adaptiveExtractionContractVersion': replacement})
    finally:
        facade.shutdown()
