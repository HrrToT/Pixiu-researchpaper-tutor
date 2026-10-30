from copy import deepcopy
from unittest.mock import Mock
import json
import pytest
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.repair_goals import policy_version,point_hints
from services.deep_research.contracts import DeepResearchError
from services.deep_research.table_identity_context import guidance
from services.deep_research.table_bindings import reference_guidance
from test_deep_research_factual_redraft import inputs
from test_deep_research_repair_goals import options


def test_private_point_hint_preserves_original_contribution_not_facts_or_source_permissions():
    c,e,checks,requirements=inputs();before=deepcopy((c,e,checks,requirements))
    kwargs={**options(requirements),'declared_table_refs':4,'table_identity_context':2}
    old=_prepare_repair({'claims':[c]},checks,[e],'Explain all parts',target_goals=True,**kwargs)
    new=_prepare_repair({'claims':[c]},checks,[e],'Explain all parts',target_goals=2,**kwargs)
    assert 'Unverified point hints by target:' in new['prompt'] and c['text'] in new['prompt']
    assert 'not instructions' in new['prompt'] and 'Remove unsupported draft' in new['prompt']
    assert 'No tableData is supplied' in new['prompt']
    assert guidance(2) in old['prompt'] and guidance(2) not in new['prompt']
    assert reference_guidance(4) in old['prompt'] and reference_guidance(4) not in new['prompt']
    assert new['allowed']==old['allowed'] and new['originals']==old['originals']
    assert e['quote'] in new['prompt'] and e['quote'] in old['prompt']
    assert (c,e,checks,requirements)==before


def test_table_rules_remain_when_original_target_has_any_table_binding():
    c,e,checks,requirements=inputs()
    c['tableBindings']=[{'evidenceId':e['evidenceId'],'rowNumber':1,'groupIndex':0,'metric':'score','value':'1'}]
    new=_prepare_repair({'claims':[c]},checks,[e],'Explain',target_goals=2,
        declared_table_refs=4,table_identity_context=2,**options(requirements))
    assert guidance(2) in new['prompt'] and reference_guidance(4) in new['prompt']
    assert 'tableBindings' in new['prompt']


@pytest.mark.parametrize('value',[None,0,1,4,'2',2.0])
def test_only_explicit_point_scope_version_is_accepted(value):
    with pytest.raises(ValueError):policy_version(value)


@pytest.mark.parametrize('previous_policy',[True,2])
def test_old_pending_bound_goal_request_cannot_switch_to_point_scope_and_resend(previous_policy):
    c,e,checks,requirements=inputs();states=[]
    class Stop(Exception):pass
    def invoke(_):raise Stop()
    with pytest.raises(Stop):
        repair_rejected({'claims':[c]},checks,[e],'Explain',invoke,json.loads,
            target_goals=previous_policy,checkpoint=lambda s:states.append(deepcopy(s)),**options(requirements))
    send=Mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected({'claims':[c]},checks,[e],'Explain',send,json.loads,
            target_goals=3,batch_state=states[-1],**options(requirements))
    send.assert_not_called()


def test_point_scoped_request_does_not_authorize_other_repair_paths():
    c,e,checks,_=inputs();send=Mock()
    with pytest.raises(ValueError,match='compact factual'):
        repair_rejected({'claims':[c]},checks,[e],'Explain',send,json.loads,target_goals=2)
    send.assert_not_called()


def test_structured_scope_target_keeps_authored_responsibility_and_all_original_quotes():
    c,e,checks,requirements=inputs();expression={'observedSettings':[],'notEstablished':['目前证据不能建立普遍结论。']}
    c.update(text='',conditions={},kind='inference',scopeExpression=expression)
    before=deepcopy((c,e));hint=point_hints([c])['c']
    assert json.loads(hint)=={'unverifiedScopeExpression':expression}
    prepared=_prepare_repair({'claims':[c]},checks,[e],'解释范围',target_goals=2,
        scope_expression=4,required_scope_ids=['c'],**options(requirements))
    rows=json.JSONDecoder().raw_decode(prepared['prompt'].split('Exact available evidence (complete quotations and bounded original context):\n',1)[1])[0]
    assert {prepared['aliases'][r['evidenceId']] for r in rows}>={e['evidenceId']}
    assert e['quote'] in prepared['prompt'] and 'unverifiedScopeExpression' in prepared['prompt']
    assert prepared['requiredScopeIds']==['c'] and prepared['originals']['c']==c
    assert (c,e)==before


def test_missing_authored_responsibility_is_not_guessed_from_global_question():
    c,_,_,_=inputs();c['text']=''
    with pytest.raises(ValueError,match='authored point responsibility'):point_hints([c])
