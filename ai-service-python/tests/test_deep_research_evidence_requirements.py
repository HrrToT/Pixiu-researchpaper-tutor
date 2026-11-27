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
        'adaptiveExtractionContractVersion': 1, 'evidenceCoverageContractVersion': 2,
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
        assert {row['criterionId'] for row in rows(prompt)} == {'input'}
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


@pytest.mark.parametrize('version,expected_new_calls', [(1, 1), (2, 0)])
def test_fulfilled_criteria_reuse_proof_after_new_unrelated_evidence(version, expected_new_calls, tmp_path):
    repo, output = store(tmp_path, evidenceCoverageContractVersion=version)
    init = evidence('The previous representation is initialization before applying the transform.', 2)
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [output, init]}})
    assert run(repo, lambda rid, node, prompt, opts: verdicts(prompt))['stop_reason'] == 'covered'
    extra = evidence('A new passage describes a rendering benchmark, without the requested input/output relationship.', 3)
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [output, init, extra]}})
    invoke = Mock(side_effect=lambda rid, node, prompt, opts: verdicts(prompt))
    assert run(repo, invoke, {'run_id': 'r', 'requery_count': 1})['stop_reason'] == 'covered'
    assert invoke.call_count == expected_new_calls


def test_saved_criterion_contract_one_cannot_be_upgraded_to_change_request_selection(tmp_path):
    repo, _ = store(tmp_path, evidenceCoverageContractVersion=1)
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run('r', lambda r: {**r, 'evidenceCoverageContractVersion': 2})


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


@pytest.mark.parametrize('replacement', [None, True, '3', 0, 1, 2])
def test_requirement_coverage_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'server.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释输入与输出',
            'deferStart': True, 'evidenceCoverageContractVersion': replacement}, start_async=False)
        assert run['evidenceCoverageContractVersion'] == 3
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'evidenceCoverageContractVersion': replacement})
    finally: facade.shutdown()
@pytest.mark.parametrize('enabled,excerpt,role', [
    (False, '各引用一条带评测条件的原文定量结果', 'joint'),
    (True, '各引用一条带评测条件的原文定量结果', 'per_paper'),
    (True, '各引用一条用于横向比较的定量结果', 'joint'),
    (True, '给出一条两篇共同的定量结果', 'joint'),
])
def test_explicit_each_paper_measurements_are_not_a_joint_comparison(enabled, excerpt, role):
    from services.deep_research.evidence_requirements import normalize_generated_requirements

    goal = {'obligationId': 'measure', 'purpose': 'answer_requirement', 'question': excerpt,
            'requiredSources': ['left', 'right'], 'requestExcerpt': excerpt,
            'comparisonRole': {'kind': 'joint', 'label': '定量结果', 'requestExcerpt': excerpt},
            'completionCriteria': [{'criterionId': 'm', 'requirement': excerpt, 'responseType': 'identification'}]}
    plan = [{'obligations': [goal]}]
    after, changes = normalize_generated_requirements(plan, '比较两篇论文，' + excerpt + '。',
        comparison_roles=True, correct_per_paper_results=enabled, complete_comparison_clauses=True,
        literal_questions=True, literal_imperatives=True, compound_questions=True)
    measurement = after[0]['obligations'][0]
    assert measurement['comparisonRole']['kind'] == role
    assert measurement['requiredSources'] == ['left', 'right']
    if role == 'per_paper':
        assert measurement['completionCriteria'][0]['responseType'] == 'identification'
    assert any(c['change'] == 'per_paper_quantitative_result_role' for c in changes) == (role == 'per_paper')
    assert goal['comparisonRole']['kind'] == 'joint'


@pytest.mark.parametrize('mode', ['joined', 'legacy', 'already_owned', 'model_only', 'matched_result'])
def test_comparison_preserves_measurements_and_joint_scope_when_plan_merges_them(mode):
    from services.deep_research.request_context import ResearchQuestion

    measurement = ('各引用一条带评测条件的原文定量结果' if mode != 'matched_result'
                   else '各引用一条用于直接比较的定量结果')
    ordering = '说明能否把两篇论文的 HPatches 数字直接用于排序'
    internal = 'D2-Net 论文内部与 SuperPoint 的比较能支持什么'
    joint = f'{ordering}，{internal}'
    excerpt = f'{measurement}。{joint}。'
    sources = ['left', 'right']
    result = {'obligationId': 'reported-results', 'purpose': 'answer_requirement',
              'question': excerpt, 'requestExcerpt': excerpt, 'requiredSources': sources,
              'comparisonRole': {'kind': 'joint', 'label': '结果和范围', 'requestExcerpt': ordering}}
    rows = [result]
    if mode == 'already_owned':
        rows.append({**result, 'obligationId': 'dedicated', 'requestExcerpt': measurement,
                     'comparisonRole': {'kind': 'per_paper', 'label': '定量结果', 'requestExcerpt': '原文定量结果'}})
    question = ResearchQuestion(excerpt, [joint] if mode == 'model_only' else [excerpt])
    after, changes = normalize_generated_requirements(
        [{'obligations': rows}], question, literal_questions=True, literal_imperatives=True,
        comparison_roles=True, compound_questions=True, joint_comparison_requests=True,
        per_paper_comparison_requests=True, complete_comparison_clauses=True,
        correct_per_paper_results=True, split_joined_per_paper_results=mode != 'legacy')
    results = after[0]['obligations']
    assert result['requestExcerpt'] == excerpt
    if mode in ('legacy', 'model_only', 'matched_result'):
        assert len(results) == 1
        assert all(c['change'] != 'split_joint_quantitative_result' for c in changes)
        return
    comparison, per_paper = results
    assert comparison['obligationId'] == 'reported-results'
    assert comparison['comparisonRole']['kind'] == 'joint'
    assert comparison['requestExcerpt'] == joint
    assert [c['requirement'] for c in comparison['completionCriteria']] == [ordering, internal]
    assert per_paper['requiredSources'] == sources
    assert per_paper['comparisonRole']['kind'] == 'per_paper'
    assert per_paper['obligationId'] == ('dedicated' if mode == 'already_owned' else 'per_paper_result')
    assert per_paper['completionCriteria'] == [
        {'criterionId': 'human_aspect_1', 'requirement': measurement, 'responseType': 'identification'}]
