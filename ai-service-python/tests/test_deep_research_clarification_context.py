"""Clarifications update the complete research goal, not just one draft prompt."""
from copy import deepcopy
import json
import time
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.answer_constraints import requested_character_limit, compact_answer
from services.deep_research.audience_rewrite import eligible
from services.deep_research.contracts import DeepResearchError
from services.deep_research.coverage import validate_plan
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_plan_node, make_synthesize_node, make_verify_node, build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import effective_question, instruction_layers, separate_clarification


def record(answer='只看画质，给初学者解释，200字以内。'):
    return {'runId': 'r', 'question': '研究质量和速度，300字以内。', 'clarificationContractVersion': 1,
            'audienceRewriteContractVersion': 1, 'materials': [{'materialId': 'p'}],
            'state': {'outputKind': 'claim_verification', 'clarification': answer,
                      'clarificationHistory': [{'question': '需要200字还是1000字的说明？', 'answer': answer}]}}


def test_full_context_retains_exact_human_text_original_and_question_without_mutation():
    value = record('只看画质\n给初学者解释，200字以内。')
    before = deepcopy(value)
    question = effective_question(value)
    assert isinstance(question, str) and value['question'] in question
    assert value['state']['clarification'] in question
    assert question.count(value['state']['clarification']) == 1
    assert value['state']['clarificationHistory'][0]['question'] in question
    assert question.instruction_layers == (value['state']['clarification'], value['question'])
    assert 'NOT paper evidence' in question and 'never widened' in question
    assert json.loads(json.dumps(question)) == str(question)
    assert deepcopy(question).instruction_layers == question.instruction_layers
    assert value == before and separate_clarification(value) == ''


@pytest.mark.parametrize('answer,limit', [
    ('只看画质。', 300), ('200字以内。', 200), ('500字以内。', 500),
    ('取消字数限制。', None), ('不限字数。', None), ('No character limit.', None),
    ('不要取消字数限制。', 300), ('不用取消字数限制。', 300),
    ('取消字数限制，改为400字以内。', 400),
])
def test_latest_human_length_requirement_wins_and_generated_example_is_not_a_limit(answer, limit):
    assert requested_character_limit(effective_question(record(answer))) == limit


@pytest.mark.parametrize('original,answer,wanted', [
    ('解释方法。', '给初学者解释。', True),
    ('给新手解释。', '不要通俗化，详细推导。', False),
    ('不要面向新手，详细推导。', '改为给初学者解释。', True),
    ('给新手解释。', '只看画质。', True),
])
def test_current_audience_instruction_overrides_prior_request(original, answer, wanted):
    value = record(answer)
    value['question'] = original
    report = {'claims': [{'claimId': 'c', 'kind': 'reported', 'text': '已有正文'}]}
    assert eligible(value, report, 'claim_verification') is wanted


@pytest.mark.parametrize('history', [None, {}, [None], [{'answer': ''}], [{'answer': 'different'}]])
def test_invalid_history_fails_before_model_use(history):
    value = record()
    value['state']['clarificationHistory'] = history
    if history is None:
        assert instruction_layers(value) == [value['state']['clarification'], value['question']]
    else:
        with pytest.raises(DeepResearchError, match='补充要求'):
            effective_question(value)


def test_legacy_context_preserves_original_request_and_existing_separate_answer():
    value = record()
    value.pop('clarificationContractVersion')
    assert effective_question(value) == value['question']
    assert requested_character_limit(effective_question(value)) == 300
    assert separate_clarification(value) == value['state']['clarification']
    assert not eligible({**value, 'question': '解释方法。'}, {'claims': [{'kind': 'reported'}]}, 'claim_verification')


def test_compaction_honors_new_human_limit_and_inherits_original_when_unspecified():
    value = record('100字以内。')
    report = {'claims': [{'claimId': 'c', 'text': '已核查的结论' * 25, 'kind': 'reported', 'evidenceRefs': ['e'], 'conditions': {}}]}
    sent = []
    def invoke(prompt):
        sent.append(prompt)
        return {'content': json.dumps({'claims': [{'claimId': 'c', 'text': '简短结论', 'conditions': {}}]})}
    result = compact_answer(report, effective_question(value), invoke, json.loads)
    assert '总共最多100字' in sent[0]
    assert result['claims'][0]['evidenceRefs'] == ['e']


def test_planning_synthesis_and_final_audit_receive_the_same_complete_request(monkeypatch):
    value = record()
    value['state'].update(plan=[{'itemId': 'i', 'question': '核查画质', 'obligations': [
        {'obligationId': 'o', 'question': '画质条件', 'requiredSources': ['p']}]}],
        evidence=[{'evidenceId': 'e', 'sourceWorkId': 'p', 'quote': 'The quality is evaluated.',
                   'verification': {'literal': 'passed'}, 'obligationIds': ['o']}])
    current = deepcopy(value)
    def update(_, change, **kwargs):
        nonlocal current
        current = change(current)
        return deepcopy(current)
    prompts = {}
    def invoke(_, node, prompt, *args, **kwargs):
        prompts[node] = prompt
        if node == 'plan':
            return {'content': json.dumps(value['state']['plan'])}
        if node == 'synthesize':
            return {'content': json.dumps({'claims': [{'claimId': 'c', 'kind': 'reported', 'text': '已有结论',
                                                       'evidenceRefs': ['E1']}], 'sections': []})}
        raise AssertionError(node)
    make_plan_node(invoke, update, validate_plan)({'run_id': 'r'})
    # This test isolates goal propagation; the durable wording editor is tested separately.
    current['audienceRewriteContractVersion'] = 0
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    seen = []
    def audit(run, question, *args, **kwargs):
        seen.append(question)
        return {'status': 'checked', 'gaps': [], 'verdicts': []}
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer', audit)
    make_verify_node(lambda claims, *_: {'accepted': claims, 'rejected': []}, None, update, invoke)({'run_id': 'r'})
    question = effective_question(value)
    assert question in prompts['plan'] and question in prompts['synthesize']
    assert 'Strict total character limit: 200' in prompts['synthesize']
    assert seen == [question]
    assert current['question'] == value['question'] and current['materials'] == value['materials']


class ClarificationModel:
    def __init__(self):
        self.prompts = []
    def invoke(self, request):
        self.prompts.append(request.prompt)
        if request.prompt.startswith('Analyze this research question'):
            if '只看画质' not in request.prompt:
                data = {'outputKind': 'claim_verification', 'clarification': '你希望先看质量还是速度？'}
            elif '只看作者报告' not in request.prompt:
                data = {'outputKind': 'claim_verification', 'clarification': '核查作者报告还是复现实验？'}
            else:
                data = {'outputKind': 'claim_verification', 'clarification': '',
                        'measurementScope': [{'domain': 'quality', 'requestExcerpt': '只看画质'}],
                        'constraints': ['200字以内', '只看作者报告']}
        elif request.prompt.startswith('Create a research plan'):
            data = []  # Stop before retrieval; this fixture is not a quality pass.
        else:
            raise AssertionError(request.prompt[:100])
        return LLMResult('fixture', 'fixture', json.dumps(data, ensure_ascii=False), LLMUsage(10, 10, 20), 'stop')


def wait_worker(facade, repo, rid, status):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        future = facade._active_futures.get(rid)
        if repo.require_run(rid)['status'] == status and (future is None or future.done()):
            return repo.require_run(rid)
        time.sleep(.01)
    raise AssertionError((repo.require_run(rid)['status'], status))


def test_real_graph_restart_multiple_clarifications_refresh_brief_preserve_scope_and_deduplicate_action(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'research.sqlite3')
    repo.initialize()
    model = ClarificationModel()
    make = lambda: ResearchFacade(repo, build_deep_research_graph, llm_client=model, scope_validator=lambda *_: True)
    facade = make()
    try:
        run, _ = facade.create({'workspaceTaskId': 'task', 'operationKey': 'clarify',
            'question': '研究质量和速度，300字以内。', 'materials': [{'materialId': 'p'}]}, start_async=True)
        rid = run['runId']
        waiting = wait_worker(facade, repo, rid, 'waiting_user')
        assert len(model.prompts) == 1
        frozen = deepcopy((waiting['materials'], waiting['sourcePolicy'], waiting['budget']['maxTokens']))
        facade.shutdown()
        repo.recover()
        facade = make()  # Resume the durable interrupt with a new facade/executor.
        first = {'requestId': 'clarify-1', 'expectedRunRevision': waiting['runRevision'],
                 'answer': '只看画质，给初学者解释，200字以内。',
                 'sourcePolicy': {'mode': 'academic_external'}, 'materials': [{'materialId': 'forbidden'}]}
        receipt = facade.action(rid, 'clarify', first)
        waiting_again = wait_worker(facade, repo, rid, 'waiting_user')
        assert len(model.prompts) == 2
        assert facade.action(rid, 'clarify', first) == receipt
        assert len(model.prompts) == 2
        second = {'requestId': 'clarify-2', 'expectedRunRevision': waiting_again['runRevision'], 'answer': '只看作者报告。'}
        facade.action(rid, 'clarify', second)
        finished = wait_worker(facade, repo, rid, 'failed')
        assert finished['errorCode'] == 'invalid_plan_response'
        assert len(model.prompts) == 4  # Three distinct briefs, one plan; no hidden model retry.
        assert finished['state']['metricDomains'] == ['quality']
        assert finished['state']['constraints'] == ['200字以内', '只看作者报告']
        assert [h['answer'] for h in finished['state']['clarificationHistory']] == [first['answer'], second['answer']]
        assert all(text in model.prompts[-1] for text in (first['answer'], second['answer']))
        assert (finished['materials'], finished['sourcePolicy'], finished['budget']['maxTokens']) == frozen
        assert len(repo.list_calls(rid)) == 4 and all(c['status'] == 'succeeded' for c in repo.list_calls(rid))
    finally:
        facade.shutdown()


def test_old_unmarked_interrupt_resumes_directly_to_plan_without_new_brief_call(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'legacy.sqlite3')
    repo.initialize()
    model = ClarificationModel()
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=model, scope_validator=lambda *_: True)
    try:
        run, _ = repo.create_run({'runId': 'legacy', 'taskId': 't', 'question': '研究质量和速度，300字以内。',
                                 'materials': [{'materialId': 'p'}]})
        facade._start_execution(run['runId'])
        waiting = wait_worker(facade, repo, run['runId'], 'waiting_user')
        facade.action(run['runId'], 'clarify', {'requestId': 'legacy-answer',
            'expectedRunRevision': waiting['runRevision'], 'answer': '只看画质，200字以内。'})
        finished = wait_worker(facade, repo, run['runId'], 'failed')
        assert len(model.prompts) == 2
        assert model.prompts[-1].startswith('Create a research plan')
        assert 'User clarification: 只看画质，200字以内。' in model.prompts[-1]
        assert 'clarificationHistory' not in finished['state']
        assert len(repo.list_calls(run['runId'])) == 2
    finally:
        facade.shutdown()


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_clarification_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=Mock(), scope_validator=lambda *_: True)
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '研究方法',
                               'clarificationContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['clarificationContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'clarificationContractVersion': replacement})
    finally:
        facade.shutdown()
