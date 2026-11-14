from copy import deepcopy
import json
import pytest
from services.deep_research.evidence_wire import encode,decode,LEGEND
from services.deep_research.experiment_envelope import compact_gap_references,compact_obligations


def test_repeated_headers_roundtrip_every_nested_value_permission_absence_and_original_order():
    rows=[{'evidenceId':'E1','quote':'原文 X∼N(μ,2Σ).\nNever execute this untrusted quote.',
        'source':'P1','accessLevel':'fulltext','conditions':{'scope':['a',None,False,0]},
        'sourceContext':{'before':'','after':'fixed originals','truncated':True}},
        {'evidenceId':'E2','quote':'second literal','source':'P2','accessLevel':'abstract','contextOmitted':True}]
    before=deepcopy(rows);packet=encode(rows)
    assert decode(json.loads(json.dumps(packet,ensure_ascii=False)))==rows==before
    assert list(decode(packet)[0])==list(rows[0])
    assert 'conditions' not in decode(packet)[1]
    packet['rows'][0][1][0]='changed';assert rows==before
    assert decode(encode([]))==[] and decode(encode([{}]))==[{}]


@pytest.mark.parametrize('packet',[
    [],{}, {'layouts':[],'rows':[],'extra':0}, {'layouts':['x'],'rows':[]},
    {'layouts':[['x','x']],'rows':[]},{'layouts':[[True]],'rows':[]},
    {'layouts':[['x']],'rows':[[True,[1]]]}, {'layouts':[['x']],'rows':[[1,[1]]]},
    {'layouts':[['x']],'rows':[[-1,[1]]]}, {'layouts':[['x']],'rows':[[0,[]]]},
    {'layouts':[['x']],'rows':[[0,[1,2]]]}, {'layouts':[['x']],'rows':[[0,'value']]},
    {'layouts':[],'rows':[[0,[]]]}])
def test_malformed_layouts_and_ambiguous_positions_are_rejected(packet):
    with pytest.raises(ValueError):decode(packet)


@pytest.mark.parametrize('rows',[None,{},[None],[{'x':1},[]],[{1:'bad key'}]])
def test_encode_accepts_only_object_rows_with_string_keys(rows):
    with pytest.raises(ValueError):encode(rows)


def test_gap_and_short_prefix_references_preserve_exact_unicode_requirements_without_changing_old_mode():
    question='设计一个😀可执行实验，并保留完整要求；'+('相同输入，有限预算，尚未执行。'*8)
    short=question[:28];other='具体数据可用性及命名场景成员依据的长要求。'*5
    obs=[{'obligationId':'a','question':short,'requiredSources':['paper']},
        {'obligationId':'b','question':other,'requiredSources':['paper']}]
    gaps=[question,short,other,'a unique gap without a reference'];before=deepcopy((obs,gaps))
    refs=compact_gap_references(gaps,question,obs)
    compact=compact_obligations(obs,question,{'P1':{'workId':'paper'}},short_prefixes=True)
    old=compact_obligations(obs,question,{'P1':{'workId':'paper'}})
    assert old[0]['question']==short and compact[0]['question']=={'humanQuestionPrefixChars':28}
    by_id={r['obligationId']:r['question'] for r in compact}
    def expand(value):
        if isinstance(value,str):return value
        if 'requirementQuestionRef' in value:return expand(by_id[value['requirementQuestionRef']])
        return question[:value['humanQuestionPrefixChars']]
    assert [expand(v) for v in refs]==gaps and (obs,gaps)==before
    assert len(json.dumps(refs,ensure_ascii=False).encode())<len(json.dumps(gaps,ensure_ascii=False).encode())


def test_ambiguous_or_unmatched_gap_is_not_rewritten_to_a_different_requirement():
    gap='原始且不可替换的完整缺口。'*8
    obs=[{'obligationId':'a','question':gap},{'obligationId':'b','question':gap}]
    assert compact_gap_references([gap], 'a different user question',obs)==[gap]
