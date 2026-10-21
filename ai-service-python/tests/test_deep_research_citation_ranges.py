from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.citation_presentation import normalize
from services.deep_research.prose_checks import leaks_internal_reference
from services.deep_research.repair import _parse_repair_response,repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_experiment_representation import prepare
from test_deep_research_shared_experiment_repair import inputs

ALIASES={f'E{i}':f'ev{i}' for i in range(1,8)}
QUOTES={a:'A literal method passage describes the operation and scene.' for a in ALIASES}


def claim(text):
    return {'claimId':'c','text':text,'conditions':{},'evidenceRefs':list(ALIASES.values()),'kind':'proposal'}


@pytest.mark.parametrize('value,expected',[
    ('处理组按论文E4-E6执行自适应操作。','处理组按所引原文执行自适应操作。'),
    ('E4-E6为论文第2阶段操作。','所引原文为论文第2阶段操作。'),
    ('E4-E6定义第2阶段操作，但设置尚未执行。','所引原文定义第2阶段操作，但设置尚未执行。'),
    ('论文E7用于展示NTC有效性。','所引原文用于展示NTC有效性。'),
    ('E7明确场景与帧窗口。','所引原文明确场景与帧窗口。'),
    ('E7仅提供场景与帧窗口。','所引原文仅提供场景与帧窗口。'),
    ('E7为flame salmon场景与帧1→2窗口。','所引原文为flame salmon场景与帧1→2窗口。'),
    ('According to paper E1–E3, use the stated operation.','According to the cited passage, use the stated operation.'),
    ('根据E1—E3所述方法选择参数。','根据所引原文所述方法选择参数。')])
def test_explicit_owned_source_markers_have_audited_display_without_new_permissions(value,expected):
    c=claim(value);before=deepcopy(c);new,audit=normalize(c,ALIASES,QUOTES,version=3)
    assert new['text']==expected and new['evidenceRefs']==c['evidenceRefs'] and c==before
    assert audit and audit['originalText']==value and audit['normalizedText']==expected
    assert all(set(r.get('evidenceRefs',[]))<=set(c['evidenceRefs']) for r in audit['removed'])
    assert not leaks_internal_reference(new,[])


@pytest.mark.parametrize('value',[
    '按E4-E6执行自适应操作。','E1、E3、E7定义第2阶段操作。',
    '论文E1-E3、E5-E7定义操作。'])
def test_explicit_action_and_list_references_are_normalized_as_a_whole(value):
    c=claim(value);new,audit=normalize(c,ALIASES,QUOTES,version=3)
    assert 'E' not in new['text'] and audit and len(audit['removed'])==1
    if 'E1-E3' in value:
        assert audit['removed'][0]['evidenceRefs']==['ev1','ev2','ev3','ev5','ev6','ev7']


@pytest.mark.parametrize('value',['按E1-E3计算差值。','按E1-E3选择。','论文E1-E3、E5-E7定义操作。'])
def test_ambiguous_actions_and_lists_with_uncited_middle_remain_unchanged(value):
    c=claim(value);c['evidenceRefs'].remove('ev6')
    assert normalize(c,ALIASES,QUOTES,version=3)==(c,None)


@pytest.mark.parametrize('value',[
    '根据E1-E3的差值作比较。','论文E1-E3用于计算比值。','根据E1-E3为场景平均误差。',
    'paper E1-E3 difference is a quantity.','x=E1-E3','E1-E3 + E7','根据E1–E3计算。',
    '`论文E1-E3`','```\n论文E1-E3\n```','$论文E1-E3$','$$论文E1-E3$$',
    '未解释的E1-E3。','论文E3-E1给出操作。'])
def test_math_code_ambiguous_and_descending_ranges_remain_unchanged(value):
    c=claim(value);assert normalize(c,ALIASES,QUOTES,version=3)==(c,None)


@pytest.mark.parametrize('change',['missing_middle','missing_endpoint','foreign','real_symbol'])
def test_range_never_borrows_an_uncited_middle_or_erases_real_source_symbols(change):
    c=claim('根据论文E1-E3操作。');quotes=deepcopy(QUOTES)
    if change=='missing_middle':c['evidenceRefs'].remove('ev2')
    elif change=='missing_endpoint':c['evidenceRefs'].remove('ev3')
    elif change=='foreign':c['text']='根据论文E1-E8操作。'
    else:quotes['E2']='The paper defines E2 as its energy variable.'
    assert normalize(c,ALIASES,quotes,version=3)==(c,None)


def test_nested_conditions_and_only_hypothesis_statement_are_normalized_with_full_audit():
    c=claim('按论文E4-E6执行。');c.update(designRole='hypothesis',conditions={'items':['E7明确场景。',{'note':'E4-E6定义操作。'}]},
        executionSpec={'statement':'按论文E4-E6执行会改变质量。','analysisClaimId':'c8',
            'effectKeys':['effect'],'purpose':'explore'})
    before=deepcopy(c);new,audit=normalize(c,ALIASES,QUOTES,version=3)
    assert 'E4' not in new['executionSpec']['statement']
    assert {k:v for k,v in new['executionSpec'].items() if k!='statement'}=={k:v for k,v in before['executionSpec'].items() if k!='statement'}
    assert audit['originalStatement']==before['executionSpec']['statement'] and audit['normalizedStatement']==new['executionSpec']['statement']
    assert c==before
    c['designRole']='groups';new,_=normalize(c,ALIASES,QUOTES,version=3)
    assert new['executionSpec']==c['executionSpec']


@pytest.mark.parametrize('version',[None,True,False,0,'3',1,2,4])
def test_old_and_unknown_versions_do_not_receive_new_source_range_rules(version):
    c=claim('按论文E4-E6执行。');assert normalize(c,ALIASES,QUOTES,version=version)==(c,None)


def test_new_repair_presentation_keeps_prompt_permissions_and_original_numeric_configs():
    old=prepare(citation_presentation_version=2);new=prepare(citation_presentation_version=3)
    assert old['prompt']==new['prompt'] and old['allowed']==new['allowed']
    patch=[{'claimId':'groups','edits':[{'op':'add','path':'/conditions',
        'value':{'context':'论文E1说明操作，但参数为拟议值。'}}]}]
    raw={'content':json.dumps(patch)};audits=[]
    result=_parse_repair_response(new,raw,json.loads,strict_response=True,presentation_audit=audits)
    assert result and 'E1' not in result[0]['conditions']['context'] and audits
    assert result[0]['executionSpec']==_parse_repair_response(old,raw,json.loads,strict_response=True)[0]['executionSpec']
    assert not result[0].get('verification')


def test_unknown_v2_repair_cannot_opt_into_v3_to_change_or_resend_its_request():
    report,checks,evidence=inputs();saved=[];invoke=Mock(side_effect=OSError('unknown'))
    args=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True)
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,citation_presentation_version=2,
            invoke_request=invoke,checkpoint=lambda s:saved.append(deepcopy(s)))
    frozen=deepcopy(saved[-1]);invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,citation_presentation_version=3,
            invoke_request=invoke,batch_state=frozen)
    invoke.assert_not_called();assert frozen==saved[-1]
