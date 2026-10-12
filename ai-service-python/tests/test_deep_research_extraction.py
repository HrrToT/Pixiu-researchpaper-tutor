import json
from unittest.mock import Mock

import pytest

from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence
from services.deep_research.tools import BudgetedSemanticChecker


def setup(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / 'r.sqlite3'))
    repo.initialize()
    reads = [{'sourceId': f's{i}', 'workId': f'p{i}', 'versionId': f'v{i}', 'contentHash': f'h{i}',
              'accessLevel': 'fulltext', 'location': {'page': i + 2}, 'obligationIds': ['o'],
              'pages': [{'text': f'Method {i} reports a complete result under the fixed evaluation condition.'}]}
             for i in range(3)]
    repo.create_run({'runId': 'r', 'taskId': 't', 'state': {'readResults': reads,
        'plan': [{'itemId': 'p', 'question': 'Compare', 'obligations': [{'obligationId': 'o', 'question': 'fixed evaluation'}]}]}})
    repo.begin_execution('r')
    return repo, reads


def test_batch_saves_calls_without_mixing_paper_locations_or_hashes(tmp_path):
    repo, reads = setup(tmp_path)
    invoke = Mock(return_value={'content': json.dumps([{'sourceId': r['sourceId'], 'quote': r['pages'][0]['text'],
        'obligationIds': ['o'], 'conditions': {'setting': 'fixed'}} for r in reads])})
    result = make_batched_extract_node(invoke, make_evidence, lambda *args: True, repo.update_run)({'run_id': 'r'})
    assert invoke.call_count == 1 and len(result['evidence_ids']) == 3
    evidence = repo.require_run('r')['state']['evidence']
    assert {(e['sourceWorkId'], e['location']['page'], e['contentHash']) for e in evidence} == {
        ('p0', 2, 'h0'), ('p1', 3, 'h1'), ('p2', 4, 'h2')}
    # An incremental pass reuses exact source+version evidence, while reassessing its goal separately.
    make_batched_extract_node(invoke, make_evidence, lambda *args: True, repo.update_run)({'run_id': 'r'})
    assert invoke.call_count == 1


def test_foreign_identity_wrong_quote_and_revoked_passage_never_become_evidence(tmp_path):
    repo, reads = setup(tmp_path)
    invoke = Mock(return_value={'content': json.dumps([
        {'sourceId': 's0', 'quote': reads[1]['pages'][0]['text'], 'obligationIds': ['o']},
        {'sourceId': 's1', 'quote': reads[1]['pages'][0]['text'], 'obligationIds': ['o']},
        {'sourceId': 'foreign', 'quote': reads[0]['pages'][0]['text'], 'obligationIds': ['o']},
    ])})
    make_batched_extract_node(invoke, make_evidence, lambda _, pid: pid != 'p1', repo.update_run)({'run_id': 'r'})
    assert not repo.require_run('r')['state']['evidence']
    assert 's1' not in {p['sourceId'] for p in json.loads(invoke.call_args.args[2].split('Passages:\n')[1])}


def test_semantic_check_accepts_fenced_json_but_not_prose():
    invoke = Mock(return_value={'content': '```json\n[{"claimId":"c","status":"passed","reason":"literal supports"}]\n```'})
    checker = BudgetedSemanticChecker(invoke, 'r')
    assert checker([{'claimId': 'c', 'evidenceRefs': []}], [])[0]['status'] == 'passed'
    invoke.return_value = {'content': 'looks correct'}
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError) as error:
        checker([{'claimId': 'c', 'evidenceRefs': []}], [])
    assert error.value.code == 'invalid_verification_response'


@pytest.mark.parametrize('response', [
    {'content': '', 'finishReason': 'length'},
    {'content': '[]'},
    {'content': '[{"claimId":"other","status":"passed"}]'},
    {'content': '[{"claimId":"c","status":"unknown"}]'},
    {'content': '[{"claimId":"c","status":"passed"}]', 'finishReason': 'length'},
])
def test_incomplete_verifier_is_failure_not_insufficient_evidence(response):
    from services.deep_research.contracts import DeepResearchError
    invoke = Mock(return_value=response)
    with pytest.raises(DeepResearchError) as error:
        BudgetedSemanticChecker(invoke, 'r')([{'claimId': 'c', 'evidenceRefs': []}], [])
    assert error.value.code == 'invalid_verification_response'
    assert invoke.call_count == 1


def test_new_snapshot_inherits_only_unchanged_authorized_source_versions(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.contracts import DeepResearchError
    repo, _ = setup(tmp_path)
    sources = [{'sourceId': 'old-a', 'workId': 'a', 'contentHash': 'ha'},
               {'sourceId': 'old-b', 'workId': 'b', 'contentHash': 'hb'},
               {'sourceId': 'public', 'workId': 'arxiv:1', 'sourceKind': 'arxiv', 'contentHash': 'hp'}]
    repo.create_run({'runId': 'parent', 'taskId': 't', 'status': 'completed', 'state': {'sources': sources,
        'evidence': [{'evidenceId': s['sourceId'], 'sourceId': s['sourceId']} for s in sources]}})
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=Mock())
    request = {'workspaceTaskId': 't', 'operationKey': 'new-snapshot', 'parentRunId': 'parent',
               'question': 'compare updated task', 'materials': [{'materialId': 'a', 'contentHash': 'ha'},
                                                               {'materialId': 'b', 'contentHash': 'changed'}]}
    child, _ = facade.create(request, start_async=False)
    assert [s['sourceId'] for s in child['state']['sources']] == ['old-a']
    assert [e['sourceId'] for e in child['state']['evidence']] == ['old-a']
    refreshed, _ = facade.create({**request, 'operationKey': 'refresh', 'question': '最新文献',
                                  'sourcePolicy': {'mode': 'academic_external'}}, start_async=False)
    assert 'public' not in {s['sourceId'] for s in refreshed['state']['sources']}
    with pytest.raises(DeepResearchError, match='本任务'):
        facade.create({**request, 'workspaceTaskId': 'other', 'operationKey': 'foreign'}, start_async=False)
    facade.shutdown()


def test_small_verifier_batches_do_not_expose_other_claims_evidence():
    prompts = []
    def invoke(**kwargs):
        prompt = kwargs['prompt']
        prompts.append(prompt)
        claims = json.loads(prompt.split('Claims:\n', 1)[1].split('\n\nEvidence:', 1)[0])
        assert kwargs['use_reserve'] is True
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'passed'} for c in claims])}
    claims = [{'claimId': f'c{i}', 'text': f'Claim {i}', 'evidenceRefs': [f'e{i}']} for i in range(3)]
    evidence = [{'evidenceId': f'e{i}', 'quote': f'UNIQUE_SOURCE_{i}'} for i in range(3)]
    result = BudgetedSemanticChecker(invoke, 'r')(claims, evidence)
    assert len(result) == len(prompts) == 3
    for i, prompt in enumerate(prompts):
        assert f'UNIQUE_SOURCE_{i}' in prompt
        assert all(f'UNIQUE_SOURCE_{j}' not in prompt for j in range(3) if j != i)


def test_large_report_has_at_most_three_verification_batches():
    batches = []
    def invoke(**kwargs):
        claims = json.loads(kwargs['prompt'].split('Claims:\n', 1)[1].split('\n\nEvidence:', 1)[0])
        batches.append(claims)
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'passed'} for c in claims])}
    claims = [{'claimId': f'c{i}', 'text': f'Claim {i}', 'evidenceRefs': []} for i in range(12)]
    result = BudgetedSemanticChecker(invoke, 'r')(claims, [])
    assert len(batches) == 3
    assert [v['claimId'] for v in result] == [c['claimId'] for c in claims]


def test_prompt_sampling_covers_other_papers_and_obligations_before_repeats():
    from services.deep_research.selection import balanced_sample
    items = [{'paper': 'a', 'obligation': 'quality', 'i': i} for i in range(25)] + [
        {'paper': 'b', 'obligation': 'quality', 'i': 1},
        {'paper': 'b', 'obligation': 'speed', 'i': 2}]
    selected = balanced_sample(items, lambda item: (item['paper'], item['obligation']), 3)
    assert [(i['paper'], i['obligation']) for i in selected] == [
        ('a', 'quality'), ('b', 'quality'), ('b', 'speed')]
    assert len(items) == 27
    assert balanced_sample([], lambda item: item, 10) == []


def test_read_balances_papers_before_legacy_source_prefix_and_prefers_new_passages(tmp_path):
    from services.deep_research.graph import make_read_node
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(str(tmp_path / 'reads.sqlite3'))
    repo.initialize()
    sources = [{'sourceId': f'a{i}', 'workId': 'A', 'contentHash': 'ha', 'text': 'old passage',
                'obligationIds': ['o']} for i in range(25)] + [
        {'sourceId': f'b{i}', 'workId': 'B', 'contentHash': 'hb', 'text': 'new passage',
         'obligationIds': ['o']} for i in range(8)]
    repo.create_run({'runId': 'read', 'taskId': 't', 'state': {'sources': sources,
        'evidence': [{'sourceId': s['sourceId'], 'contentHash': 'ha'} for s in sources[:25]]}})
    repo.begin_execution('read')
    read = Mock(side_effect=lambda rid, sid: {'pages': [{'page': 1, 'text': sid}]})
    make_read_node(read, lambda *a: True, repo.update_run)({'run_id': 'read', 'source_ids': [s['sourceId'] for s in sources]})
    chosen = [s['workId'] for s in repo.require_run('read')['state']['readResults']]
    assert chosen.count('A') == chosen.count('B') == 6
    assert read.call_count == 12
