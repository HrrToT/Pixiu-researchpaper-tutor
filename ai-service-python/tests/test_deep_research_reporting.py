from copy import deepcopy

from services.deep_research.reporting import render_report, conversation_summary, verification_notice


def test_verification_notice_does_not_claim_factual_checks_for_proposals_or_empty_results():
    assert verification_notice([]) == ''
    assert verification_notice([{'kind': 'proposal'}]) == '假设与实验建议尚未经过实验验证。'
    assert verification_notice([{'kind': 'inference'}]) == '推断限于所列证据和适用条件。'
    assert verification_notice([{'kind': 'reported'}, {'kind': 'hypothesis'}]) == (
        '论文事实已按所列原文核对。假设与实验建议尚未经过实验验证。')


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


def test_external_access_scope_comes_from_cited_evidence_not_other_downloads():
    claims = [{'claimId': 'c', 'kind': 'reported', 'text': '摘要中的方法说明。', 'evidenceRefs': ['a']}]
    evidence = [{'evidenceId': 'a', 'sourceKind': 'arxiv', 'accessLevel': 'abstract'},
                {'evidenceId': 'unused', 'sourceKind': 'arxiv', 'accessLevel': 'fulltext'}]
    body = render_report({'claims': claims, 'evidence': evidence})
    summary = conversation_summary(claims, 'partial', evidence=evidence)
    assert '本回答引用：摘要。' in body and '本回答引用：摘要。' in summary
    assert '全文片段' not in body and '全文片段' not in summary


def test_fulltext_and_abstract_are_distinguished_without_claiming_complete_reading():
    claims = [{'claimId': 'c', 'text': '已核对的分工。', 'evidenceRefs': ['f', 'a']}]
    evidence = [{'evidenceId': 'f', 'sourceKind': 'arxiv', 'accessLevel': 'fulltext', 'location': {'page': 4}},
                {'evidenceId': 'a', 'sourceKind': 'arxiv', 'accessLevel': 'abstract'}]
    body = render_report({'claims': claims, 'evidence': evidence})
    assert '本回答引用：全文片段、摘要。' in body
    assert '第 4 页 · 全文片段' in body
    assert '已阅读全文' not in body
    summary = conversation_summary(claims, 'partial', evidence=evidence, max_chars=90)
    assert len(summary) <= 90 and '已核对的分工。' in summary


def analysis_claim(identity, text, evidence):
    from services.deep_research.execution_materialization import materialize_execution_claim
    return materialize_execution_claim({'claimId': identity, 'kind': 'proposal',
        'designRole': 'analysis', 'designContractVersion': 2, 'text': text,
        'evidenceRefs': [evidence], 'conditions': {'scope': identity}, 'executionSpec': {
            'effects': {'interaction': 'L11-L10-L01+L00'},
            'uncertainty': {'mode': 'paired_cluster_bootstrap', 'unit': 'scene',
                            'repetitions': 1000, 'confidence': 0.95, 'seed': 42},
            'decision': {'mode': 'interval_excludes_zero'}}})


def test_identical_generated_analysis_protocol_renders_once_preserving_prose_sources_and_conditions():
    claims = [analysis_claim('a', 'Estimate the interaction.', 'e1'),
              analysis_claim('b', 'A non-significant result is not equivalence.', 'e2')]
    payload = {'outputKind': 'experiment_design', 'claims': claims, 'evidence': [
        {'evidenceId': 'e1', 'quote': 'First source.'}, {'evidenceId': 'e2', 'quote': 'Second source.'}]}
    before = deepcopy(payload)
    body = render_report(payload)
    assert body.count('效应定义：') == 1
    assert 'Estimate the interaction.' in body and 'A non-significant result is not equivalence.' in body
    assert 'scope：a' in body and 'scope：b' in body
    assert '[1](#research-evidence-e1)' in body and '[2](#research-evidence-e2)' in body
    assert 'First source.' in body and 'Second source.' in body
    assert payload == before


def test_different_analysis_configuration_and_unrecognized_suffix_are_not_hidden():
    from services.deep_research.execution_materialization import materialize_execution_claim
    first = analysis_claim('a', 'First.', 'e')
    second = deepcopy(first)
    second.update(claimId='b', text='Second.')
    second['executionSpec']['uncertainty']['confidence'] = 0.9
    second = materialize_execution_claim(second)
    body = render_report({'outputKind': 'experiment_design', 'claims': [first, second]})
    assert body.count('效应定义：') == 2 and '95%' in body and '90%' in body
    altered = analysis_claim('c', 'Different original prose.', 'e')
    altered['text'] += '\nAn original extra sentence after the generated protocol.'
    body = render_report({'claims': [first, altered]})
    assert body.count('效应定义：') == 2
    assert 'An original extra sentence' in body


def test_inconclusive_experiment_does_not_blame_source_insufficiency_by_default():
    body = render_report({'outputKind': 'experiment_design', 'claims': []})
    summary = conversation_summary([], 'inconclusive', output_kind='experiment_design')
    assert '尚未形成通过核验的实验方案' in body and '尚未形成通过核验的实验方案' in summary
    assert '证据不足' not in body and '证据不足' not in summary
    assert '尚未形成通过核验的结论' in conversation_summary([], 'inconclusive')
    assert '证据不足' not in render_report({'claims': []})


def test_same_rendered_assumptions_do_not_hide_different_typed_configurations():
    from services.deep_research.execution_materialization import materialize_execution_claim
    first = analysis_claim('a', 'First.', 'e')
    first['text'] = 'First.'
    first['executionSpec']['uncertainty'] = {'mode': 'analytic', 'method': 'Paired analysis',
                                           'assumptions': ['A；B'], 'confidence': 0.95}
    second = deepcopy(first)
    second.update(claimId='b', text='Second.')
    second['executionSpec']['uncertainty']['assumptions'] = ['A', 'B']
    claims = [materialize_execution_claim(first), materialize_execution_claim(second)]
    body = render_report({'claims': claims})
    assert body.count('效应定义：') == 2


def test_no_external_citations_adds_no_access_banner():
    from services.deep_research.reporting import source_access_summary
    assert source_access_summary([], [{'evidenceId': 'unused', 'sourceKind': 'arxiv'}]) == ''
    assert source_access_summary([{'evidenceRefs': ['local']}], [
        {'evidenceId': 'local', 'accessLevel': 'fulltext', 'sourceKind': 'local'}]) == ''
