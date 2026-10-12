from copy import deepcopy

from services.deep_research.reporting import render_report, conversation_summary


def test_repeated_audit_gaps_are_folded_without_mutating_full_record():
    payload = {'claims': [{'claimId': 'c', 'text': '已经核实的核心回答。', 'kind': 'reported'}],
        'gaps': [
            {'obligationId': 'o', 'question': '输入条件', 'missingEvidence': '尚未核实'},
            {'obligationId': 'o', 'question': '输入条件', 'missingEvidence': '最终回答尚未完整回应', 'stage': 'answer'},
            {'obligationId': 'answer_scope', 'question': '冗长的原始问题', 'wholeQuestion': True},
        ]}
    before = deepcopy(payload)
    body = render_report(payload)
    assert '<summary>还有 1 项未完成</summary>' in body
    assert body.count('输入条件') == 1
    assert '冗长的原始问题' not in body and '已经核实的核心回答。' in body
    assert body.index('已经核实的核心回答。') < body.index('<details>')
    assert payload == before


def test_whole_question_gap_is_not_hidden_when_it_is_the_only_gap():
    body = render_report({'gaps': [{'question': '尚未回应的用户要求', 'wholeQuestion': True}]})
    assert '尚未回应的用户要求' in body
    assert '<summary>还有 1 项未完成</summary>' in body


def test_partial_summary_does_not_claim_the_cause_is_missing_evidence():
    summary = conversation_summary([{'text': '原文支持的结果。'}], 'partial')
    assert '结果尚不完整' in summary and '证据缺口' not in summary
