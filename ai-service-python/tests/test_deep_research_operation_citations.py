"""Presentation-only normalization must never invent ownership or fix science."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.citation_presentation import normalize
from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair import _parse_repair_response, repair_rejected
from test_deep_research_citation_ranges import ALIASES, QUOTES, claim
from test_deep_research_experiment_representation import prepare
from test_deep_research_shared_experiment_repair import inputs


@pytest.mark.parametrize('verb', ['初始化', '优化', '训练', '更新', '构建', '恢复'])
def test_owned_method_citation_keeps_the_actual_action_and_all_permissions(verb):
    c=claim(f'新增状态按E1-E3、E5{verb}，参数仍为拟议选择。')
    original=deepcopy(c)
    result,audit=normalize(c,ALIASES,QUOTES,version=4)
    assert result['text']==f'新增状态按所引原文{verb}，参数仍为拟议选择。'
    assert result['evidenceRefs']==c['evidenceRefs'] and c==original
    assert audit['removed'][0]['evidenceRefs']==['ev1','ev2','ev3','ev5']
    assert normalize(c,ALIASES,QUOTES,version=3)==(c,None)


@pytest.mark.parametrize('left,right', [('（','）'), ('(',')')])
def test_parenthesized_explicit_method_citations_are_normalized_in_text_and_conditions(left,right):
    c=claim(f'执行自适应步骤{left}按E1-E3{right}。')
    c['conditions']={'context':'新增状态按E1-E3初始化与优化，且不传到下一帧。'}
    c['executionSpec']={'factors':[{'name':'E1-E3', 'value':0.01}]}
    original=deepcopy(c)
    result,audit=normalize(c,ALIASES,QUOTES,version=4)
    assert result['text']==f'执行自适应步骤{left}按所引原文{right}。'
    assert result['conditions']=={'context':'新增状态按所引原文初始化与优化，且不传到下一帧。'}
    assert result['executionSpec']==c['executionSpec'] and result['evidenceRefs']==c['evidenceRefs']
    assert len(audit['removed'])==2 and c==original
    assert not result.get('verification')


@pytest.mark.parametrize('text',[
    '按E1-E3计算差值。', '按E1-E3选择。', '按E1-E3的比值初始化。',
    '（按E1-E3 + E5）', 'x=(E1-E3)', '$按E1-E3初始化$', '`按E1-E3初始化`',
    '按E3-E1训练。', '按E1-E8优化。', '根据P1训练。', '（E1-E3）',
])
def test_math_ambiguous_nonowned_or_protected_material_is_not_rewritten(text):
    c=claim(text)
    assert normalize(c,ALIASES,QUOTES,version=4)==(c,None)


@pytest.mark.parametrize('change',['uncited_middle','uncited_endpoint','source_symbol'])
def test_every_range_member_must_be_owned_and_must_not_be_a_real_source_symbol(change):
    c=claim('按E1-E3初始化。');quotes=deepcopy(QUOTES)
    if change=='uncited_middle':c['evidenceRefs'].remove('ev2')
    elif change=='uncited_endpoint':c['evidenceRefs'].remove('ev3')
    else:quotes['E2']='Let E2 be the energy function.'
    assert normalize(c,ALIASES,quotes,version=4)==(c,None)


def test_repair_uses_same_permissions_and_parameters_and_records_originals():
    old=prepare(citation_presentation_version=3);new=prepare(citation_presentation_version=4)
    assert new['prompt']==old['prompt'] and new['allowed']==old['allowed']
    patch=[{'claimId':'groups','edits':[{'op':'add','path':'/conditions',
        'value':{'context':'按E1初始化，参数尚未验证。'}}]}]
    response={'content':json.dumps(patch)};audit=[]
    result=_parse_repair_response(new,response,json.loads,strict_response=True,presentation_audit=audit)
    assert result[0]['conditions']=={'context':'按所引原文初始化，参数尚未验证。'}
    assert result[0]['executionSpec']==new['originals']['groups']['executionSpec']
    assert audit[0]['originalConditions']=={'context':'按E1初始化，参数尚未验证。'}


def test_unknown_v3_repair_cannot_upgrade_and_resend():
    report,checks,evidence=inputs();saved=[];invoke=Mock(side_effect=OSError('unknown'))
    args=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True)
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,citation_presentation_version=3,
            invoke_request=invoke,checkpoint=lambda s:saved.append(deepcopy(s)))
    frozen=deepcopy(saved[-1]);invoke.reset_mock()
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,citation_presentation_version=4,
            invoke_request=invoke,batch_state=frozen)
    invoke.assert_not_called();assert frozen==saved[-1]
