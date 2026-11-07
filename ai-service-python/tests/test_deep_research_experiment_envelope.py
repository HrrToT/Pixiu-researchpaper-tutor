from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.experiment_envelope import (
    BASIS_BYTES,DIRECT_PLAN_OPTION,compact_obligations,two_arm_request,
)
from services.deep_research.experiment_planning import prepare_plan,basis_limit,validate_basis,planning_prompt
from services.deep_research.graph import make_synthesize_node
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_experiment_planning import Store,current,basis,response


def compact_record():
    record=current();record['experimentDraftContractVersion']=4
    return record


def test_requirement_compaction_roundtrips_without_losing_human_source_or_role_constraints():
    question='Human original requirement and exact scope. '*12
    sources={'P1':{'workId':'a-long-original-source-work-identity'}}
    obligations=[{'obligationId':'whole','question':question,'requestExcerpt':question[:250],
        'requiredSources':['a-long-original-source-work-identity','unavailable-version'],
        'completionCriteria':[{'criterionId':'state','requirement':'Complete actual state, not an opaque blob.'}]},
        {'obligationId':'other','question':'Another distinct requirement.','requiredSources':['unavailable-version']}]
    before=deepcopy((obligations,sources));compact=compact_obligations(obligations,question,sources)
    assert len(json.dumps(compact).encode())<len(json.dumps(obligations).encode())
    restored=deepcopy(compact)
    for item in restored:
        for key in ('question','requestExcerpt'):
            if isinstance(item.get(key),dict):item[key]=question[:item[key]['humanQuestionPrefixChars']]
        item['requiredSources']=[sources[ref['sourceRef']]['workId'] if isinstance(ref,dict) else ref
            for ref in item['requiredSources']]
    assert restored==obligations and (obligations,sources)==before
    # An ambiguous work identity cannot silently choose one version.
    sources['P2']={'workId':sources['P1']['workId']}
    assert compact_obligations(obligations,question,sources)[0]['requiredSources'][0]==sources['P1']['workId']


@pytest.mark.parametrize('question,expected',[
    ('两组分别跳过或执行第二阶段，比较整体成本。',True),
    ('Use two groups: skip or execute the extra stage.',True),
    ('Two groups with and without the proposed package.',True),
    ('两组单因素比较。',True),('四组两因素，不只报告两组。',False),
    ('A two-factor 2x2 study with four groups.',False),('Compare several methods.',False)])
def test_two_arm_scope_avoids_inventing_four_group_requirements(question,expected):
    assert two_arm_request(question) is expected


def test_direct_profile_is_idempotent_reserved_before_send_and_keeps_old_low_request():
    from llm.provider import LLMResult,LLMUsage
    old=research_model_options('plan_experiment',{'max_tokens':6144,'temperature':0.0})
    new=research_model_options('plan_experiment',{'max_tokens':6144,'temperature':0.0,DIRECT_PLAN_OPTION:True})
    assert new=={**old,'thinking':{'type':'disabled'},'reasoning_effort':'none'}
    assert research_model_options('plan_experiment',new)==new and new['max_tokens']==old['max_tokens']==6144
    with pytest.raises(ValueError):research_model_options('verify',{DIRECT_PLAN_OPTION:True})
    with pytest.raises(ValueError):research_model_options('plan_experiment',{DIRECT_PLAN_OPTION:'yes'})
    store=Store(compact_record());provider=Mock()
    provider.invoke.return_value=LLMResult(content=response()['content'],provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False))
    invoke=TrackedLLMInvoker(provider,reserve,Mock(),request_options=research_model_options,
        run_record_fn=lambda _:store.value)
    plan=prepare_plan(store.value,prompt='actual original source',aliases={'E1':'eq'},
        invoke=lambda node,prompt,extra:invoke('r',node,prompt,extra,use_reserve=True),
        parse=json.loads,checkpoint=store.checkpoint)
    sent=provider.invoke.call_args.args[0]
    assert sent.extra_body['thinking']=={'type':'disabled'} and DIRECT_PLAN_OPTION not in sent.extra_body
    assert reserve.call_args.kwargs['args_digest']==digest(plan['request'])
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(sent.prompt.encode())+1024+6144


def test_smaller_private_plan_limit_preserves_invalid_raw_response_without_fallback():
    value=basis();value['protocol']['state']='x'*2200
    assert validate_basis(value,{'E1':'eq'}) and not validate_basis(value,{'E1':'eq'},max_bytes=BASIS_BYTES)
    store=Store(compact_record());invoke=Mock(return_value=response(value))
    with pytest.raises(DeepResearchError):prepare_plan(store.value,prompt='original source',aliases={'E1':'eq'},
        invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)
    assert basis_limit(store.value)==2500 and store.value['state']['experimentPlanning']['status']=='invalid_response'
    assert store.value['state']['experimentPlanning']['response']==response(value)
    with pytest.raises(DeepResearchError):prepare_plan(store.value,prompt='original source',aliases={'E1':'eq'},
        invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)
    assert invoke.call_count==1


def test_new_prompt_preserves_original_quotes_while_old_planning_prompt_bytes_are_unchanged():
    question='两组分别跳过或执行共享流程的第二阶段。'+'保持数据和初始化相同。'*15
    kwargs=dict(question=question,obligations=[{'obligationId':'o','question':question}],
        sources={'P1':{'workId':'w'}},evidence=[{'evidenceId':'E1','quote':'Exact source operation.'}],tables={},metric_domains=None)
    old=planning_prompt(**kwargs);new=planning_prompt(**kwargs,compact=True)
    assert 'Statistical reference (only for two binary factors)' in old
    assert 'Statistical reference (only for two binary factors)' not in new
    assert 'fit2500UTF-8' in new and 'exact gap in unresolved' in new
    assert 'Exact source operation.' in new and 'humanQuestionPrefixChars' in new
    assert old==planning_prompt(**kwargs) and 'fit4000UTF-8' in old


def test_new_graph_still_uses_both_original_source_requests_and_all_config_roles():
    store=Store(compact_record());invoke=Mock(side_effect=[response(),{'finishReason':'length'}])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert result=={'error_code':'invalid_synthesis_response'}
    assert [call.args[1] for call in invoke.call_args_list]==['plan_experiment','synthesize']
    for call in invoke.call_args_list:
        assert 'h = f(x, t + n)' in call.args[2] and len(call.args[2].encode())<=24000
    assert invoke.call_args_list[0].args[3]['reasoning_effort']=='none'
    assert 'baselineInitialization' in invoke.call_args_list[1].args[2]
    assert store.value['state']['experimentPlanning']['verification']=='unchecked'


def test_explicit_shared_module_premise_is_not_displaced_by_incidental_table_rows():
    from test_deep_research_synthesis_premises import evidence
    record=compact_record();record['question']='两组分别跳过或执行第二阶段，固定共享的 ABC 模块结果。'
    original=evidence('module','The ABC module learns transformations; the same trained state initializes both groups.')
    record['state']['evidence']=[evidence('other'+str(i),'Table caption: Aggregate benchmark measurements.') for i in range(24)]+[original]
    before=deepcopy(record['state']['evidence']);store=Store(record)
    invoke=Mock(side_effect=[response(),{'finishReason':'length'}])
    # Fixture sourceFacts must cite the actual routing alias, never an extra source.
    def call(_id,node,prompt,extra,**_kw):
        if node=='plan_experiment':return response({**basis(),'sourceFacts':[]})
        return {'finishReason':'length'}
    invoke.side_effect=call
    make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert invoke.call_count==2
    for request in invoke.call_args_list:
        assert original['quote'] in request.args[2]
    assert store.value['state']['evidence']==before
