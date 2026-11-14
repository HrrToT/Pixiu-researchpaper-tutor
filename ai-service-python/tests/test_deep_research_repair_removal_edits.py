from copy import deepcopy
import json,hashlib
from unittest.mock import Mock
import pytest
from services.deep_research.repair_removals import materialize
from services.deep_research.repair import _parse_repair_response
from services.deep_research.verification import verify_claims
from test_deep_research_repair_removals import prepared,row


def test_declared_edit_is_applied_before_kind_transition_and_still_needs_source_review():
    p,e=prepared(5);before=deepcopy((p,e));audit=[]
    value=row('约束预测差异，从而贴近真实表面。',['从而贴近真实表面'])
    value['kind']='inference';value['draftingBasis']['scopeDecision']='bounded_inference'
    revised=_parse_repair_response(p,{'content':json.dumps([value])},json.loads,drafting_audit=audit)
    assert revised[0]['text']=='约束预测差异。' and revised[0]['kind']=='inference'
    assert 'discardedDraftSpans' not in revised[0] and 'draftRemovalEdit' not in revised[0]
    edit=audit[0]['draftRemovalEdit']
    assert edit['inputText']==value['text'] and edit['outputText']==revised[0]['text']
    assert edit['inputSha256']==hashlib.sha256(value['text'].encode()).hexdigest()
    assert edit['verification']=='unchecked' and edit['offsetUnit']=='unicode_code_point'
    assert [x['removed'] for x in edit['edits']]==['，','从而贴近真实表面']
    semantic=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'No inherited approval.'}])
    assert not verify_claims(revised,[e],semantic)['accepted'];semantic.assert_called_once()
    assert (p,e)==before


@pytest.mark.parametrize('text,spans',[
    ('重复重复',['重复']),('aaa',['aa']),('abcdef',['bcd','cde']),
    ('保留。',['来源外的文字']),('删除全部。',['删除全部']),
    ('文字',['文字','文字']),('文字','文字'),
])
def test_ambiguous_overlapping_foreign_and_emptying_edits_are_rejected(text,spans):
    with pytest.raises(ValueError):materialize({'text':text,'discardedDraftSpans':spans},{'text':text})


def test_only_edit_boundaries_receive_punctuation_cleanup():
    text='原有，。保留观点，删除尾句。另一个观点；删除效果。'
    result,_,audit=materialize({'text':text,'discardedDraftSpans':['删除尾句','删除效果']},{'text':text})
    assert result=='原有，。保留观点。另一个观点。'
    replay=text
    for edit in reversed(audit['edits']):
        assert text[edit['start']:edit['end']]==edit['removed']
        replay=replay[:edit['start']]+replay[edit['end']:]
    assert replay==result


def test_already_removed_spans_and_empty_declaration_do_not_add_edits_or_support():
    revised='保留作用。'
    result,_,audit=materialize({'text':revised,'discardedDraftSpans':['无依据效果']},{'text':'保留作用，无依据效果。'})
    assert result==revised and not audit['edits'] and audit['alreadyRemovedSpans']==['无依据效果']
    assert materialize({'text':revised,'discardedDraftSpans':[]},{'text':revised})[0]==revised


def test_legacy_contract_four_still_rejects_a_retained_declared_span():
    p,_=prepared(4)
    assert _parse_repair_response(p,{'content':json.dumps([row('约束预测差异，从而贴近真实表面。')])},json.loads)==[]


def test_edit_audit_is_retained_even_when_private_drafting_basis_is_absent():
    p,_=prepared(5);audit=[];value=row('约束预测差异，从而贴近真实表面。',['从而贴近真实表面'])
    value.pop('draftingBasis')
    result=_parse_repair_response(p,{'content':json.dumps([value])},json.loads,drafting_audit=audit)
    assert result and audit[0]['basis'] is None and audit[0]['draftRemovalEdit']['verification']=='unchecked'
