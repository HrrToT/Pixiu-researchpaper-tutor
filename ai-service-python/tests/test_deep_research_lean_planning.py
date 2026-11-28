from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_planning import prepare_plan,validate_basis,planning_prompt,basis_limit,SPLIT_GUIDANCE
from services.deep_research.graph import make_synthesize_node
from test_deep_research_experiment_planning import Store,current,basis,response


def lean_basis():
    old=basis()
    return {'sourceRefs':['E1'],'protocol':old['protocol'],'unresolved':old['unresolved']}


def record():
    r=current();r['experimentDraftContractVersion']=5
    return r


def prepare(store,invoke):
    return prepare_plan(store.value,prompt='exact original scientific input',aliases={'E1':'original'},
        invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)


def test_lean_basis_retains_all_protocol_decisions_with_original_evidence_index():
    value=lean_basis();before=deepcopy(value)
    assert validate_basis(value,{'E1':'original'},max_bytes=2500,lean=True)
    assert not validate_basis(value,{'E1':'original'},max_bytes=2500)
    assert not validate_basis(basis(),{'E1':'original'},max_bytes=2500,lean=True)
    store=Store(record());invoke=Mock(return_value=response(value));plan=prepare(store,invoke)
    assert plan['basis']==value==before and plan['verification']=='unchecked'
    assert basis_limit(store.value)==2500 and plan['request']['extra']['max_tokens']==6144
    assert plan['request']['extra']['reasoning_effort']=='none'
    again=prepare(store,invoke)
    assert again==plan and invoke.call_count==1


@pytest.mark.parametrize('variant',['foreign','duplicate','missing_decision','extra_fact_prose','oversize'])
def test_bad_lean_basis_is_saved_and_never_retried_or_coerced(variant):
    value=lean_basis()
    if variant=='foreign':value['sourceRefs']=['foreign']
    if variant=='duplicate':value['sourceRefs']=['E1','E1']
    if variant=='missing_decision':value['protocol'].pop('data')
    if variant=='extra_fact_prose':value['sourceFacts']=basis()['sourceFacts']
    if variant=='oversize':value['protocol']['state']='x'*2500
    store=Store(record());invoke=Mock(return_value=response(value))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    saved=deepcopy(store.value['state']['experimentPlanning'])
    assert saved['response']==response(value) and saved['status']=='invalid_response'
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1 and store.value['state']['experimentPlanning']==saved


def test_unknown_lean_send_keeps_pending_and_does_not_invent_a_received_plan():
    store=Store(record());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    assert store.value['state']['experimentPlanning']['status']=='pending'
    assert 'response' not in store.value['state']['experimentPlanning']


def test_new_graph_keeps_original_evidence_full_grammar_and_separate_split_axes():
    store=Store(record());original=deepcopy(store.value['state']['evidence'])
    invoke=Mock(side_effect=[response(lean_basis()),{'finishReason':'length'}])
    assert make_synthesize_node(invoke,store.update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
    assert [c.args[1] for c in invoke.call_args_list]==['plan_experiment','synthesize']
    for call in invoke.call_args_list:
        assert SPLIT_GUIDANCE in call.args[2] and original[0]['quote'] in call.args[2]
        assert len(call.args[2].encode())<=24000
    planner,body=invoke.call_args_list
    assert 'Do NOT repeat source quotations or paper-fact summaries' in planner.args[2]
    assert 'sourceRefs' in planner.args[2] and 'fit2500UTF-8' in planner.args[2]
    assert 'stateDefinitions' in body.args[2] and 'baselineInitialization' in body.args[2]
    assert json.dumps(lean_basis(),ensure_ascii=False,separators=(',',':')) in body.args[2]
    assert store.value['state']['evidence']==original
    assert store.value['state']['experimentPlanning']['verification']=='unchecked'


def test_old_version_four_prompt_and_failed_response_remain_unchanged():
    kwargs={'question':'两组固定相同模块，跳过或执行第二阶段','obligations':[],
            'sources':{},'evidence':[],'tables':{},'metric_domains':None,'compact':True}
    old=planning_prompt(**kwargs);new=planning_prompt(**kwargs,lean=True)
    assert 'sourceFacts' in old and SPLIT_GUIDANCE not in old
    assert SPLIT_GUIDANCE in new and 'sourceRefs' in new
    assert old==planning_prompt(**kwargs)
