from copy import deepcopy
import re
import pytest

from services.deep_research.comparison_presentation import metadata
from services.deep_research.reporting import render_report, visible_answer_character_count


def fixture():
    layout = [
        {'obligationId': 'mechanism', 'question': '压缩机制', 'source': 'P1', 'claimIds': ['a']},
        {'obligationId': 'mechanism', 'question': '压缩机制', 'source': 'P2', 'claimIds': ['b']},
    ]
    draft = {'sources': {'P1': {'title': 'Method A', 'workId': 'A', 'versionId': 'a-v1'},
                         'P2': {'title': 'Method B', 'workId': 'B', 'versionId': 'b-v1'}},
             'layout': layout}
    claims = [
        {'claimId': 'a', 'kind': 'reported', 'text': '剪除冗余基元。',
         'conditions': {'条件': '保持相同数据与预算'}, 'evidenceRefs': ['e-a']},
        {'claimId': 'b', 'kind': 'reported', 'text': '量化属性。', 'conditions': {}, 'evidenceRefs': ['e-b']},
        {'claimId': 'joint', 'kind': 'inference', 'text': '需结合部署条件选择。',
         'conditions': {}, 'evidenceRefs': ['e-a', 'e-b']},
        {'claimId': 'advice', 'kind': 'proposal', 'text': '建议在目标设备核对速度。',
         'conditions': {}, 'evidenceRefs': ['e-a', 'e-b']},
    ]
    return {'comparisonCells': metadata(draft), 'claims': claims, 'evidence': [],
            'outputKind': 'paper_comparison', 'presentationVersion': 4}


def test_common_renderer_orders_judgement_table_advice_and_keeps_each_condition_and_citation():
    payload = fixture(); before = deepcopy(payload)
    text = render_report(payload)
    assert text.index('需结合部署条件选择') < text.index('| 比较维度') < text.index('建议在目标设备核对速度')
    assert 'Method A' in text and 'Method B' in text
    assert '(#research-evidence-e-a' in text and '(#research-evidence-e-b' in text
    assert text.count('剪除冗余基元。') == 1
    assert '保持相同数据与预算' in text
    assert payload == before


def test_rejected_cell_is_not_reintroduced_from_layout_or_draft_metadata():
    payload = fixture(); payload['claims'] = payload['claims'][:1]
    text = render_report(payload)
    assert '量化属性。' not in text and '尚未形成可核验结论' in text
    assert '| 比较维度' in text
    payload['claims'] = []
    text = render_report(payload)
    assert '| 比较维度' not in text and '本次尚未形成通过核验的结论' in text


def test_table_cell_escaping_preserves_math_and_cannot_create_another_row_or_html():
    payload = fixture(); payload['claims'][0]['text'] = r'$\alpha|x$' + '\n<script>unsafe</script>'
    text = render_report(payload)
    assert r'\alpha' in text and '&#124;' in text
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert '<br>' in text
    assert len([line for line in text.splitlines() if line.startswith('| ')]) == 3


def test_publication_counting_and_prepublication_counting_use_the_same_table():
    from services.deep_research.answer_constraints import visible_count
    payload = fixture(); payload['characterLimit'] = 500
    count = visible_answer_character_count(payload)
    expected = len(re.sub(r'\s+', '', render_report(payload, _counting=True)))
    assert count == expected
    candidate = {'claims': payload['claims'], 'comparisonCells': payload['comparisonCells']}
    assert visible_count(candidate, 500, 'paper_comparison', (), 4) == count
    assert 'Method A' in render_report(payload, _counting=True)
    assert '#research-evidence-' not in render_report(payload, _counting=True)


def test_over_limit_table_is_reported_by_existing_publication_format_gate():
    from services.deep_research.answer_format import publication_format_gaps
    payload = fixture()
    record = {'question': '20字以内比较', 'answerFormatContractVersion': 3,
              'reportPresentationContractVersion': 4}
    gaps = publication_format_gaps(record, payload['claims'], [], display_payload=payload)
    assert any(g.get('actualCharacterCount', 0) > 20 for g in gaps)


def test_short_titles_have_full_bibliographic_tooltips_and_stay_in_counted_layout():
    payload = fixture(); full = 'A' * 100
    payload['comparisonCells']['sources']['P1']['title'] = full
    text = render_report(payload)
    assert 'A' * 35 + '…' in text and full in text
    counted = render_report(payload, _counting=True)
    assert 'A' * 35 + '…' in counted and full not in counted


def test_version_labels_require_a_verified_publication_identity():
    from services.deep_research.publication_identity import from_verified_pages
    payload=fixture()
    for alias,rev in [('P1',2),('P2',4)]:
        source=payload['comparisonCells']['sources'][alias]
        source['title']='Same Paper';source['versionId']='hash-'+alias
        source['publicationIdentity']=from_verified_pages({'contentHash':source['versionId']},
            [{'page':1,'text':f'arXiv:2401.00001v{rev}'}])
    text=render_report(payload)
    assert 'Same Paper (v2)' in text and 'Same Paper (v4)' in text
    payload['comparisonCells']['sources']['P1']['publicationIdentity']['revision']='v99'
    assert '(v99)' not in render_report(payload)


@pytest.mark.parametrize('tampered',[False,True])
def test_actual_publication_uses_verified_cells_and_rechecks_source_binding(tampered):
    from unittest.mock import Mock
    from services.deep_research.graph import make_publish_node
    payload=fixture();claims=deepcopy(payload['claims'][:2]);meta=payload['comparisonCells']
    if tampered:claims[0]['evidenceRefs']=['e-b']
    ev=[{'evidenceId':'e-a','sourceWorkId':'A','sourceVersionId':'a-v1','quote':'A result.'},
        {'evidenceId':'e-b','sourceWorkId':'B','sourceVersionId':'b-v1','quote':'B result.'}]
    record={'question':'500字以内比较','comparisonCellsContractVersion':1,
            'authoredBodyContractVersion':3,'scopeExpressionContractVersion':5,
            'factualPromptContractVersion':3,'synthesisEvidenceContractVersion':6,
            'synthesisInputContractVersion':2,'draftValidationContractVersion':1,
            'reportPresentationContractVersion':4,'answerFormatContractVersion':3,
            'state':{'outputKind':'paper_comparison','plan':[],'gaps':[],'evidence':ev,
                     'comparisonCellDraft':{'sources':meta['sources'],'layout':meta['layout']},
                     'reportBody':{'claims':claims,'comparisonCells':meta},
                     'verifiedReport':{'verifiedClaims':claims,'rejectedClaims':[],
                                       'answerCoverage':{'status':'not_requested','gaps':[]}}}}
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    publish=Mock(return_value=({'publicationId':'p'},True))
    make_publish_node(publish,update)({'run_id':'r','report_version_id':'v'})
    final=publish.call_args.kwargs['payload'];text=publish.call_args.kwargs['report_text']
    assert final['comparisonCells']==meta and '| 比较维度' in text
    assert '量化属性。' in text
    if tampered:
        assert '剪除冗余基元。' not in text and '尚未形成可核验结论' in text
        assert [c['claimId'] for c in final['claims']]==['b']
        assert record['state']['verifiedReport']['rejectedClaims'][-1]['reason']=='comparison_cell_source_mismatch'
    else:
        assert [c['claimId'] for c in final['claims']]==['a','b']
        assert '保持相同数据与预算' in text


def test_generation_verification_and_publication_share_the_same_cell_layout():
    import json
    from unittest.mock import Mock
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node,make_verify_node,make_publish_node
    _,_,record=node_capture(3)
    record.update(comparisonCellsContractVersion=1,authoredBodyContractVersion=3,
                  scopeExpressionContractVersion=5,draftValidationContractVersion=1,
                  synthesisInputContractVersion=2,reportPresentationContractVersion=4,
                  answerFormatContractVersion=3)
    record['question']='比较两篇论文的机制。'
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def generate(rid,node,prompt,options,**kw):
        assert node=='synthesize'
        cells=json.JSONDecoder().raw_decode(prompt.split(
            'Cell routing and citation permissions (metadata, not evidence):\n',1)[1])[0]
        return {'content':json.dumps({'cells':[{'cellId':c['cellId'],'unresolved':False,
            'claims':[{'kind':'reported','body':{'prose':{'text':'测量深度用于三维重建。','conditions':{}}},
                       'evidenceRefs':[c['evidenceIds'][0]],'tableBindings':[],'detailLevel':'fulltext'}]}
            for c in cells],'conclusions':[]})}
    make_synthesize_node(generate,update)({'run_id':'r'})
    before=deepcopy(record['state']['reportBody']['comparisonCells'])
    # Fixture verifier checks graph plumbing only; this is not scientific acceptance.
    checker=Mock(side_effect=lambda cs,ev,semantic:{'accepted':deepcopy(cs),'rejected':[]})
    make_verify_node(checker,None,update)({'run_id':'r'})
    publish=Mock(return_value=({'publicationId':'p'},True))
    make_publish_node(publish,update)({'run_id':'r','report_version_id':'v'})
    payload=publish.call_args.kwargs['payload']
    assert 'comparisonPresentationDigest' in record['state']['verifiedReport']['answerCoverage']
    assert record['state']['verifiedReport']['answerCoverage']['status'] != 'invalidated_comparison_presentation'
    assert payload['comparisonCells']==before
    assert len(payload['claims'])==2 and '| 比较维度' in publish.call_args.kwargs['report_text']
    assert publish.call_args.kwargs['report_text'].count('测量深度用于三维重建。')==2
    assert payload['outcome']!='complete'  # No real final-answer audit was supplied.


def test_final_audit_receives_only_accepted_table_and_binds_its_current_identity():
    import json
    from unittest.mock import Mock
    from services.deep_research.final_coverage import audit_final_answer
    from services.deep_research.comparison_presentation import audit_view, revalidate_audit
    payload = fixture(); claims = payload['claims'][:1]; meta = payload['comparisonCells']
    plan = [{'obligations': [{'obligationId': 'mechanism', 'question': '压缩机制'}]}]
    invoke = Mock(return_value={'content': '[]'})
    audit = audit_final_answer('r', '比较压缩机制', plan, claims, [], invoke, json.loads,
                              comparison_cells=meta)
    prompt = invoke.call_args.args[2]
    assert 'Server-rendered comparison presentation' in prompt
    assert '剪除冗余基元。' in prompt and '量化属性。' not in prompt
    assert '尚未形成可核验结论' in prompt and 'Method B' in prompt
    assert audit_view(meta, claims)['layout'][1]['claimIds'] == []
    assert revalidate_audit(audit, meta, claims) == audit
    for mutate in ('title', 'identity', 'routing', 'claims'):
        changed = deepcopy(meta); accepted = deepcopy(claims)
        if mutate == 'title': changed['sources']['P1']['title'] = 'Changed title'
        if mutate == 'identity': changed['sources']['P1']['versionId'] = 'a-v2'
        if mutate == 'routing': changed['layout'][0]['source'] = 'P2'
        if mutate == 'claims': accepted[0]['text'] = 'Changed result'
        invalid = revalidate_audit(audit, changed, accepted)
        assert invalid['status'] == 'invalidated_comparison_presentation'
        assert invalid['gaps'][-1]['wholeQuestion']


def test_comparison_layout_bytes_are_admitted_before_any_coverage_call():
    import json
    from unittest.mock import Mock
    from services.deep_research.final_coverage import audit_final_answer
    payload = fixture(); meta = payload['comparisonCells']
    meta['sources']['P1']['title'] = '论文标题' * 10000
    invoke = Mock()
    audit = audit_final_answer('r', '比较',
        [{'obligations': [{'obligationId': 'mechanism', 'question': '机制'}]}],
        payload['claims'], [], invoke, json.loads, comparison_cells=meta)
    invoke.assert_not_called()
    assert audit['status'] == 'budget_exhausted'
    assert audit['budgetLimit']['kind'] == 'coveragePromptBytes'


def test_legacy_final_audit_has_no_comparison_contract_or_prompt_changes():
    import json
    from unittest.mock import Mock
    from services.deep_research.final_coverage import audit_final_answer
    payload = fixture(); invoke = Mock(return_value={'content': '[]'})
    audit = audit_final_answer('r', '比较',
        [{'obligations': [{'obligationId': 'mechanism', 'question': '机制'}]}],
        payload['claims'], [], invoke, json.loads)
    assert 'comparisonPresentationDigest' not in audit
    assert 'Server-rendered comparison presentation' not in invoke.call_args.args[2]


@pytest.mark.parametrize('uncompiled_claims', [False, True])
def test_no_cell_draft_after_budget_stop_preserves_evidence_and_publishes_only_gap(uncompiled_claims):
    from unittest.mock import Mock
    from services.deep_research.graph import make_verify_node, make_publish_node
    payload = fixture()
    evidence = [{'evidenceId': 'e-a', 'sourceWorkId': 'A', 'sourceVersionId': 'a-v1',
                 'quote': 'The acquired evidence stays available.'}]
    record = {'question': '比较两篇论文', 'comparisonCellsContractVersion': 1,
              'authoredBodyContractVersion': 3, 'scopeExpressionContractVersion': 5,
              'factualPromptContractVersion': 3, 'synthesisEvidenceContractVersion': 6,
              'synthesisInputContractVersion': 2, 'draftValidationContractVersion': 1,
              'reportPresentationContractVersion': 4,
              'state': {'outputKind': 'paper_comparison', 'plan': [], 'gaps': [],
                        'evidence': evidence, 'stopReason': 'assessment_unavailable'}}
    if uncompiled_claims:
        record['state']['reportBody'] = {'claims': payload['claims'][:1]}
    def update(rid, fn, **kwargs):
        nonlocal record
        record = fn(deepcopy(record))
        return deepcopy(record)
    checker = Mock(side_effect=AssertionError('No uncompiled content may reach semantic approval'))
    model = Mock(side_effect=AssertionError('No answer exists to audit'))
    make_verify_node(checker, None, update, model)({'run_id': 'r'})
    assert record['state']['verifiedReport']['verifiedClaims'] == []
    if uncompiled_claims:
        assert record['state']['verifiedReport']['rejectedClaims'][0]['reason'] == 'comparison_cell_draft_missing'
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    make_publish_node(publish, update)({'run_id': 'r', 'report_version_id': 'v'})
    final = publish.call_args.kwargs['payload']
    assert not final['claims'] and 'comparisonCells' not in final
    assert final['outcome'] != 'complete' and record['state']['evidence'] == evidence
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_comparison_presentation'
    checker.assert_not_called(); model.assert_not_called()
