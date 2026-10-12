import json
from unittest.mock import Mock

from services.deep_research.answer_constraints import compact_answer, requested_character_limit


def test_bounded_compaction_retains_claim_identity_before_reverification():
    claim = {'claimId': 'c', 'text': '很长的结论' * 30, 'kind': 'reported', 'evidenceRefs': ['e']}
    compact = {'sections': [], 'claims': [{**claim, 'text': '测试条件下画质接近，仍有损失。'}]}
    invoke = Mock(return_value={'content': json.dumps(compact)})
    assert compact_answer({'claims': [claim]}, '两点，80字以内', invoke, json.loads) == compact
    invoke.assert_called_once()
    assert requested_character_limit('不超过300字') == 300


def test_compaction_cannot_change_sources_or_evade_length_with_conditions():
    claim = {'claimId': 'c', 'text': '很长的结论' * 30, 'kind': 'reported', 'evidenceRefs': ['e']}
    invoke = Mock(return_value={'content': json.dumps({'claims': [{**claim, 'text': '简短', 'evidenceRefs': ['foreign']}]})})
    assert compact_answer({'claims': [claim]}, '80字以内', invoke, json.loads) is None
    invoke.return_value = {'content': json.dumps({'claims': [{**claim, 'text': '简短', 'conditions': {'重复': '条件' * 100}}]})}
    assert compact_answer({'claims': [claim]}, '80字以内', invoke, json.loads) is None


def test_unconstrained_or_short_answers_do_not_add_paid_calls():
    report = {'claims': [{'claimId': 'c', 'text': '短结论'}]}
    invoke = Mock()
    assert compact_answer(report, '80字以内', invoke, json.loads) is report
    assert compact_answer(report, '详细比较', invoke, json.loads) is report
    invoke.assert_not_called()


def test_string_conditions_are_preserved_before_length_and_evidence_checks():
    report = {'claims': [{'claimId': 'c', 'text': '结论', 'conditions': '只在当前测试设置下'}]}
    invoke = Mock()
    result = compact_answer(report, '80字以内', invoke, json.loads)
    assert result['claims'][0]['conditions'] == {'context': '只在当前测试设置下'}
    invoke.assert_not_called()


def test_compaction_can_drop_secondary_claims_but_retains_kept_identity():
    important = {'claimId': 'answer', 'kind': 'inference', 'text': '需要保留的判断' * 20, 'evidenceRefs': ['e']}
    secondary = {'claimId': 'extra', 'kind': 'reported', 'text': '不影响判断的背景' * 20, 'evidenceRefs': ['e2']}
    compact = {'claims': [{**important, 'text': '当前证据不足以支持普遍结论。'}]}
    invoke = Mock(return_value={'content': json.dumps(compact)})
    assert compact_answer({'claims': [important, secondary]}, '100字以内', invoke, json.loads) == compact
    assert 'MAY DROP' in invoke.call_args.args[0]


def test_list_conditions_are_preserved_without_wasting_a_compaction_call():
    report = {'claims': [{'text': '摘要提出三部分方法。', 'conditions': ['仅摘要', '未读取全文']}]}
    invoke = Mock()
    result = compact_answer(report, '300字以内', invoke, json.loads)
    assert result['claims'][0]['conditions'] == {'1': '仅摘要', '2': '未读取全文'}
    invoke.assert_not_called()
