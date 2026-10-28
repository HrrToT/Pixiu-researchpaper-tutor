from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.answer_constraints import compact_answer
from services.deep_research.answer_format import requested_points, publication_format_gaps
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_publish_node, make_synthesize_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import ResearchQuestion


@pytest.mark.parametrize('question,count,mode', [
    ('解释原因，只写三点，350字以内。', 3, 'exact'), ('分两点解释', 2, 'exact'),
    ('只列出4条', 4, 'exact'), ('用十二点来说明', 12, 'exact'),
    ('最多五点', 5, 'max'), ('分三点以内', 3, 'max'),
    ('Use exactly 3 bullet points.', 3, 'exact'), ('No more than 2 points', 2, 'max'),
])
def test_explicit_display_count(question, count, mode):
    assert requested_points(question) == {'count': count, 'mode': mode}


@pytest.mark.parametrize('question', ['论文有三点贡献，请解释第二点。', '不要只写三点。',
    '实验只规划一个子问题。', 'Do not use exactly 3 points.', '先阅读三篇论文。'])
def test_subject_counts_and_negated_instructions_do_not_create_display_counts(question):
    assert requested_points(question) is None


def test_only_human_layers_create_format_and_latest_override_or_cancel_wins():
    combined = '模型建议只写八点。父成果说只写十点。'
    assert requested_points(ResearchQuestion(combined, ['只写两点', '只写三点']))['count'] == 2
    assert requested_points(ResearchQuestion(combined, ['不用分点', '只写三点'])) is None
    assert requested_points(ResearchQuestion(combined, ['解释第二点'])) is None
    assert requested_points('只写两点，改成一段') is None
    assert requested_points('不用分点，改为只写三点')['count'] == 3


def claims(count):
    return [{'claimId': str(i), 'text': f'第{i}个已核实解释。', 'kind': 'reported',
             'evidenceRefs': ['e'], 'verification': 'semantic_passed'} for i in range(count)]


def publish_record(count=2, **updates):
    c = claims(count)
    record = {'question': '只写三点，350字以内', 'answerFormatContractVersion': 1,
              'state': {'outputKind': 'claim_verification', 'plan': [], 'gaps': [], 'evidence': [],
                'verifiedReport': {'verifiedClaims': c, 'rejectedClaims': [],
                                   'answerCoverage': {'status': 'checked', 'gaps': [], 'verdicts': []}}}, **updates}
    return record


@pytest.mark.parametrize('count,expected', [(2, 'partial'), (3, 'complete'), (4, 'partial')])
def test_false_semantic_complete_cannot_override_actual_display_count(count, expected):
    record = publish_record(count)
    def update(rid, fn, **kwargs):
        nonlocal record
        record = fn(deepcopy(record)); return deepcopy(record)
    publish = Mock(return_value=({'publicationId': 'pub'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r'})
    assert result['outcome'] == expected
    payload = publish.call_args.kwargs['payload']
    assert payload['claims'] == claims(count)  # No padding, merging or fact loss.
    if count != 3:
        assert payload['gaps'][0]['actualPointCount'] == count
        assert payload['gaps'][0]['wholeQuestion']
    else:
        assert payload['gaps'] == []


def test_format_is_rechecked_after_repairs_and_does_not_change_legacy_publication():
    record = publish_record()
    sections = [{'title': '判断', 'claimIds': ['0', '1', '0']},
                {'title': '适用条件', 'claimIds': ['0']}]
    c = claims(2)
    assert publication_format_gaps(record, c, sections)[0]['actualPointCount'] == 2
    record.pop('answerFormatContractVersion')
    assert publication_format_gaps(record, c, sections) == []
    record['answerFormatContractVersion'] = 1
    record['question'] = '最多三点，50字以内'
    assert not publication_format_gaps(record, c, sections)
    c[0]['conditions'] = {'条件': '长' * 100}
    gap = publication_format_gaps(record, c, sections)[0]
    assert gap['expectedCharacterLimit'] == 50
    assert gap['stage'] == 'answer_format'


def test_compaction_shortens_all_requested_points_without_truncating_to_two():
    before = claims(3)
    for row in before:
        row['text'] *= 20
    patches = [{'claimId': row['claimId'], 'text': '已核实的解释', 'conditions': {}} for row in before]
    invoke = Mock(return_value={'content': json.dumps({'claims': patches})})
    result = compact_answer({'claims': before}, '只写三点，100字以内', invoke, json.loads, preserve_claims=True)
    assert [c['claimId'] for c in result['claims']] == ['0', '1', '2']
    assert '必须保留每个输入ID' in invoke.call_args.args[0]
    invoke.return_value = {'content': json.dumps({'claims': patches[:2]})}
    assert compact_answer({'claims': before}, '只写三点，100字以内', invoke, json.loads, preserve_claims=True) is None


def test_extra_list_markup_cannot_hide_inside_three_claims():
    record = publish_record(3)
    c = claims(3)
    c[0]['text'] += '\n- 额外的第四点。'
    gaps = publication_format_gaps(record, c, [{'claimIds': ['0', '1', '2']}])
    assert gaps and gaps[0]['question'] == '按要求整理分点结构'


def test_synthesis_does_not_force_two_claims_against_three_point_short_request():
    record = publish_record(3)
    record['question'] = '只写三点，250字以内'
    def update(rid, fn, **kwargs):
        nonlocal record
        record = fn(deepcopy(record)); return deepcopy(record)
    captured = []
    def invoke(rid, node, prompt, options, **kwargs):
        captured.append(prompt)
        return {'content': json.dumps({'claims': claims(3), 'sections': []})}
    result = make_synthesize_node(invoke, update)({'run_id': 'r'})
    assert not result.get('error_code')
    assert len(captured) == 1 and 'At most 3 claims' in captured[0]
    assert 'exactly 3 distinct answer points' in captured[0]


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 3])
def test_format_contract_cannot_be_selected_by_client_or_changed_after_creation(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '只写三点',
            'answerFormatContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['answerFormatContractVersion'] == 2
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'answerFormatContractVersion': replacement})
    finally:
        facade.shutdown()
