from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.adaptive_assessment import assess
from services.deep_research.coverage import coverage_gaps
from services.deep_research.evidence_requirements import normalize_generated_requirements
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import ResearchQuestion
from services.deep_research.verification import make_evidence


def plan():
    return [{'itemId': 'i', 'question': 'Explain the method', 'obligations': [
        {'obligationId': 'o', 'question': 'What is predicted and how is the previous state used?',
         'requestExcerpt': 'what is predicted, how is the previous state used',
         'requiredSources': ['paper'], 'completionCriteria': [
             {'criterionId': 'output', 'requirement': 'Identify the predicted output', 'responseType': 'identification'},
             {'criterionId': 'input', 'requirement': 'Explain use of the previous state', 'responseType': 'explanation'}]}]}]


def evidence(text, page=1, paper='paper'):
    result = make_evidence({'workId': paper, 'versionId': paper + '-v1', 'contentHash': 'h', 'accessLevel': 'fulltext'},
        text, text, location={'page': page}, obligation_ids=['o'])
    result['sourceId'] = f'{paper}-{page}'
    return result


def store(tmp_path, **extra):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    ev = evidence('The predictor outputs a translation and rotation.')
    repo.create_run({'runId': 'r', 'taskId': 't', 'adaptiveResearchContractVersion': 1,
        'adaptiveExtractionContractVersion': 1, 'evidenceCoverageContractVersion': 1,
        'materials': [{'materialId': 'paper'}], 'state': {'plan': plan(), 'evidence': [ev],
        'sources': [{'sourceId': 's', 'workId': 'paper'}]}, **extra})
    repo.begin_execution('r')
    return repo, ev


def run(repo, invoke, state=None):
    return assess(state or {'run_id': 'r'}, repo.require_run('r'), repo.update_run, invoke, coverage_gaps)


def rows(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Pairs:\n', 1)[1])[0]


def verdicts(prompt):
    return {'content': json.dumps([{'pairId': row['pairId'], 'relevant':
        (row['criterionId'] == 'output' and 'outputs' in row['quote']) or
        (row['criterionId'] == 'input' and 'initialization' in row['quote'])} for row in rows(prompt)])}


def test_output_relevance_cannot_close_a_separate_conditioning_requirement(tmp_path):
    repo, ev = store(tmp_path)
    invoke = Mock(side_effect=lambda rid, node, prompt, opts: verdicts(prompt))
    result = run(repo, invoke)
    assert result['gaps'] and result['stop_reason'] != 'covered'
    saved = repo.require_run('r')['state']
    coverage = saved['coverage'][0]
    assert coverage['state'] == 'unchecked' and coverage['checked'] is True
    assert coverage['criteria'][0]['evidenceIds'] == [ev['evidenceId']]
    assert coverage['criteria'][1]['evidenceIds'] == []
    assert 'previous state' in result['gaps'][0]['missingEvidence']
    assert saved['plan'][0]['status'] == 'gap'
    assert all('criterionId' in row for row in rows(invoke.call_args.args[2]))
    assert 'NOT approval of a final answer' in invoke.call_args.args[2]


def test_new_input_passage_completes_all_aspects_without_rechecking_settled_pairs(tmp_path):
    repo, ev = store(tmp_path)
    first = run(repo, lambda rid, node, prompt, opts: verdicts(prompt))
    added = evidence('The previous frame representation is reused as initialization before applying the predicted transform.', 2)
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [ev, added]}})
    seen = []
    def invoke(rid, node, prompt, opts):
        seen.append(prompt)
        assert ev['quote'] not in prompt and added['quote'] in prompt
        return verdicts(prompt)
    result = run(repo, invoke, {'run_id': 'r', 'requery_count': 0,
        'prev_assessment_evidence_digest': first['prev_assessment_evidence_digest']})
    assert result['stop_reason'] == 'covered' and not result['gaps']
    assert len(seen) == 1
    assert all(row['evidenceIds'] for row in repo.require_run('r')['state']['coverage'][0]['criteria'])
    assert run(repo, lambda *_: pytest.fail('No repeated request'))['stop_reason'] == 'covered'
    assert all(e['verification']['semantic'] == 'unchecked' for e in repo.require_run('r')['state']['evidence'])


def test_another_papers_input_cannot_close_the_requested_papers_input(tmp_path):
    repo, ev = store(tmp_path)
    other = evidence('The previous state is initialization.', 2, paper='foreign')
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [ev, other]}})
    def invoke(rid, node, prompt, opts):
        assert other['quote'] not in prompt
        return verdicts(prompt)
    assert run(repo, invoke)['gaps']


def test_compiled_graph_reads_remaining_local_input_before_new_search(tmp_path):
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.coverage import validate_plan
    from services.deep_research.graph import build_deep_research_graph
    repo, _ = store(tmp_path)
    repo.update_run('r', lambda r: {**r, 'question': 'Explain the input and output',
        'state': {**r['state'], 'evidence': [], 'sources': [], 'readResults': []}})
    texts = ['The predictor outputs a translation and rotation for each scene entity.',
             'Background passage unrelated to the requested research method.',
             'A second unrelated passage describes the rendering benchmark.',
             'The previous frame representation is initialization before applying the predicted transform.']
    searches, batches = [], []
    def retrieve(query, pdf_id, limit=5):
        searches.append(query)
        return [{'sourceId': f's{i}', 'text': text, 'sourceWorkId': 'paper', 'versionId': 'paper-v1',
                 'accessLevel': 'fulltext', 'location': {'page': i+1}} for i, text in enumerate(texts)]
    def invoke(rid, node, prompt, options, **kwargs):
        if node == 'resolve_brief': content = {'outputKind': 'claim_verification', 'clarification': ''}
        elif node == 'plan': content = plan()
        elif node == 'extract':
            passages = json.loads(prompt.split('Passages:\n', 1)[1]); batches.append([p['sourceId'] for p in passages])
            content = [{'sourceId': p['sourceId'], 'quote': p['text'], 'obligationIds': ['o'], 'conditions': {}}
                       for p in passages if 'outputs' in p['text'] or 'initialization' in p['text']]
        elif node == 'assess_relevance': return verdicts(prompt)
        elif node == 'synthesize': raise DeepResearchError('fixture_stop', 'Inspect acquisition only')
        else: pytest.fail(node)
        return {'content': json.dumps(content), 'finishReason': 'stop'}
    graph = build_deep_research_graph(llm_invoke=invoke, retrieve_fn=retrieve,
        read_fn=lambda rid, sid: {'accessLevel': 'fulltext', 'pages': [{'page': int(sid[1:])+1, 'text': texts[int(sid[1:])]}]},
        scope_validator=lambda *_: True, make_evidence_fn=make_evidence, coverage_gaps_fn=coverage_gaps,
        verify_claims_fn=lambda *_: {}, repo_update=repo.update_run, repo_publish=repo.publish_report,
        validate_plan_fn=validate_plan, extract_batch_size=3)
    with pytest.raises(DeepResearchError, match='acquisition only'):
        graph.invoke({'run_id': 'r', 'execution_epoch': 1})
    assert batches == [['s0', 's1', 's2'], ['s3']] and len(searches) == 1
    assert not repo.require_run('r')['state']['gaps']
    assert all(row['evidenceIds'] for row in repo.require_run('r')['state']['coverage'][0]['criteria'])


@pytest.mark.parametrize('response', [
    [{'evidenceId': 'e', 'obligationId': 'o', 'relevant': True}],
    [{'pairId': 'R1', 'relevant': True}],
    [{'pairId': 'R1', 'relevant': True}, {'pairId': 'R1', 'relevant': False}],
    [{'pairId': 'R1', 'relevant': 'true'}, {'pairId': 'R2', 'relevant': True}],
])
def test_ambiguous_legacy_tuples_or_missing_criterion_verdicts_never_close_gaps(tmp_path, response):
    repo, _ = store(tmp_path)
    result = run(repo, lambda *_: {'content': json.dumps(response)})
    assert result['gaps'] and repo.require_run('r')['state']['assessmentStatus'] == 'unchecked'
    run(repo, lambda *_: pytest.fail('No malformed response resend'))


def test_unknown_response_keeps_the_exact_frozen_request_and_is_not_reissued(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    repo, _ = store(tmp_path)
    provider = Mock(); provider.invoke.side_effect = LLMProviderError('unknown', provider='fixture', model='fixture')
    invoke = TrackedLLMInvoker(provider, repo.reserve_call, repo.complete_call)
    with pytest.raises(LLMProviderError): run(repo, invoke)
    with pytest.raises(UnknownCallError): run(repo, invoke)
    assert provider.invoke.call_count == 1 and repo.list_calls('r')[0]['status'] == 'unknown'


def test_only_literal_human_aspects_are_split_and_unprovided_examples_removed():
    original = plan()
    o = original[0]['obligations'][0]
    o['question'] = 'What changes (e.g. scale, color) and how is the prior state used?'
    o['completionCriteria'] = [{'criterionId': 'c', 'requirement': 'Identify changes (e.g. scale, color) and prior-state use',
                               'responseType': 'explanation'}]
    saved = deepcopy(original)
    result, changes = normalize_generated_requirements(original,
        ResearchQuestion('Unverified parent artifact: what is predicted, how is the previous state used',
                         ['Explain what is predicted, how is the previous state used.']))
    criteria = result[0]['obligations'][0]['completionCriteria']
    assert [row['requirement'] for row in criteria] == ['what is predicted', 'how is the previous state used']
    assert [row['responseType'] for row in criteria] == ['identification', 'explanation']
    assert 'scale' not in result[0]['obligations'][0]['question'] and changes
    assert original == saved
    ungrounded, _ = normalize_generated_requirements(original,
        ResearchQuestion('what is predicted, how is the previous state used', ['Explain the second point.']))
    assert len(ungrounded[0]['obligations'][0]['completionCriteria']) == 1


def test_examples_the_human_actually_supplied_and_ordinary_lists_are_retained():
    original = plan()
    o = original[0]['obligations'][0]
    o['question'] = '说明变化（如位置、旋转），以及前一帧怎样使用。'
    o['requestExcerpt'] = '说明变化（如位置、旋转），以及前一帧怎样使用'
    result, _ = normalize_generated_requirements(original, o['question'])
    assert '（如位置、旋转）' in result[0]['obligations'][0]['question']
    assert len(result[0]['obligations'][0]['completionCriteria']) == 2


def test_literal_aspects_preserve_parenthesized_lists_and_decimal_values():
    original = plan()
    excerpt = '预测什么变化（如坐标，旋转），怎样在1.2秒内利用前一帧表示'
    original[0]['obligations'][0]['requestExcerpt'] = excerpt
    result, _ = normalize_generated_requirements(original, excerpt)
    assert [c['requirement'] for c in result[0]['obligations'][0]['completionCriteria']] == [
        '预测什么变化（如坐标，旋转）', '怎样在1.2秒内利用前一帧表示']


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_requirement_coverage_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'server.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释输入与输出',
            'deferStart': True, 'evidenceCoverageContractVersion': replacement}, start_async=False)
        assert run['evidenceCoverageContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'evidenceCoverageContractVersion': replacement})
    finally: facade.shutdown()
