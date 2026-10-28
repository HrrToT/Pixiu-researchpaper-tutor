from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.factual_reasoning import OPTION, request_options
from services.deep_research.runtime import research_model_options


@pytest.mark.parametrize('kind',['claim_verification','paper_comparison'])
def test_only_new_short_factual_answers_choose_reasoning(kind):
    record={'factualReasoningContractVersion':1}
    assert request_options(record,'给出判断，300字以内。',kind)=={OPTION:True}
    for value in [None,True,False,0,8,'1']:
        assert request_options({'factualReasoningContractVersion':value},'300字以内',kind)=={}
    for question in ['详细说明','301字以内','0字以内']:
        assert request_options(record,question,kind)=={}


@pytest.mark.parametrize('kind',['experiment_design','direction_survey',None])
def test_other_outputs_keep_existing_profile_even_when_short(kind):
    assert request_options({'factualReasoningContractVersion':1},'200字以内',kind)=={}


def test_legacy_role_options_and_repair_caps_are_preserved():
    assert research_model_options('synthesize',{})=={
        'thinking':{'type':'disabled'},'reasoning_effort':'none','max_tokens':16384,
        'response_format':{'type':'json_object'}}
    assert research_model_options('repair_claims',{'_repair_output_limit':4096})=={
        'thinking':{'type':'disabled'},'reasoning_effort':'none','max_tokens':4096}
    new=research_model_options('repair_claims',{OPTION:True,'_repair_output_limit':4096})
    assert new=={'thinking':{'type':'enabled'},'reasoning_effort':'low','max_tokens':4096}
    assert OPTION not in new and '_repair_output_limit' not in new
    assert research_model_options('verify',{OPTION:True})['reasoning_effort']=='high'
    assert research_model_options('extract',{OPTION:True,'max_tokens':1500})=={
        'thinking':{'type':'disabled'},'reasoning_effort':'none','max_tokens':1500}


def test_v2_keeps_synthesis_reasoning_but_uses_direct_bounded_repair_without_fallback_call():
    from services.deep_research.factual_reasoning import DIRECT_REPAIR_OPTION
    flags=request_options({'factualReasoningContractVersion':2},'200字以内','claim_verification')
    assert flags=={OPTION:True,DIRECT_REPAIR_OPTION:True}
    synth=research_model_options('synthesize',flags)
    repair=research_model_options('repair_claims',{**flags,'_repair_output_limit':4096})
    assert synth['thinking']=={'type':'enabled'} and synth['max_tokens']==8192
    assert repair=={'thinking':{'type':'disabled'},'reasoning_effort':'none','max_tokens':4096}
    assert DIRECT_REPAIR_OPTION not in synth and DIRECT_REPAIR_OPTION not in repair


def test_new_options_are_reserved_fingerprinted_and_reused_before_provider_send():
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.tools import TrackedLLMInvoker
    provider=Mock();provider.invoke.return_value=LLMResult(content='{}',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False));complete=Mock()
    tracked=TrackedLLMInvoker(provider,reserve,complete,request_options=research_model_options)
    options={OPTION:True,'max_tokens':4000};before=deepcopy(options)
    tracked('r','synthesize','short judgement',options,use_reserve=True)
    assert options==before
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(b'short judgement')+1024+8192
    sent=provider.invoke.call_args.args[0].extra_body
    assert sent['max_tokens']==8192 and sent['thinking']=={'type':'enabled'}
    assert OPTION not in sent and sent['reasoning_effort']=='low'
    fingerprint=reserve.call_args.kwargs['args_digest']
    reserve.return_value=({'callId':'c','result':{'content':'settled response'}},True)
    result=tracked('r','synthesize','short judgement',options,use_reserve=True)
    assert result['content']=='settled response' and provider.invoke.call_count==1
    assert reserve.call_args.kwargs['args_digest']==fingerprint
    reserve.return_value=({'callId':'d','reservationToken':'s'},False)
    tracked('r','synthesize','short judgement',{'max_tokens':4000},use_reserve=True)
    assert reserve.call_args.kwargs['args_digest']!=fingerprint


@pytest.mark.parametrize('replacement',[None,True,False,0,1,2,'1'])
def test_policy_is_server_owned_immutable_and_not_client_selected(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'200字以内',
            'deferStart':True,'factualReasoningContractVersion':replacement},start_async=False)
        assert p['factualReasoningContractVersion']==7
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(p['runId'],lambda r:{**r,'factualReasoningContractVersion':replacement})
    finally: facade.shutdown()


def test_actual_synthesis_node_selects_profile_and_truncation_remains_failure():
    from services.deep_research.graph import make_synthesize_node
    record={'factualReasoningContractVersion':1,'question':'核查这个结论，200字以内。',
            'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_rid,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    llm=Mock(return_value={'content':'','finishReason':'length'})
    result=make_synthesize_node(llm,update)({'run_id':'r'})
    assert result=={'error_code':'invalid_synthesis_response'}
    assert llm.call_count==1 and llm.call_args.args[3][OPTION] is True


def test_v3_changes_only_short_factual_synthesis_effort_with_same_output_and_direct_repair():
    from services.deep_research.factual_reasoning import HIGH_SYNTHESIS_OPTION
    old=request_options({'factualReasoningContractVersion':2},'200字以内','paper_comparison')
    new=request_options({'factualReasoningContractVersion':3},'200字以内','paper_comparison')
    old_synth=research_model_options('synthesize',old);new_synth=research_model_options('synthesize',new)
    assert new_synth=={**old_synth,'reasoning_effort':'high'}
    assert old_synth['max_tokens']==new_synth['max_tokens']==8192
    assert research_model_options('repair_claims',{**new,'_repair_output_limit':4096})==research_model_options('repair_claims',{**old,'_repair_output_limit':4096})
    assert HIGH_SYNTHESIS_OPTION not in new_synth
    assert request_options({'factualReasoningContractVersion':3},'200字以内','experiment_design')=={}


def test_v4_uses_same_bounded_profile_for_a_longer_multi_paper_comparison_only():
    record={'factualReasoningContractVersion':4,'materialSnapshot':{'materialRefs':['paperA','paperB']}}
    flags=request_options(record,'比较输入、时间表示、训练与FPS可比性，450字以内。','paper_comparison')
    old_short=request_options({'factualReasoningContractVersion':3},'200字以内','paper_comparison')
    assert flags==old_short
    assert research_model_options('synthesize',flags)['max_tokens']==8192
    assert research_model_options('synthesize',flags)['reasoning_effort']=='high'
    for version in (1,2,3):
        assert request_options({**record,'factualReasoningContractVersion':version},'450字以内','paper_comparison')=={}
    for question,kind in [('701字以内','paper_comparison'),('450字以内','claim_verification'),
                          ('450字以内','experiment_design'),('详细比较','paper_comparison')]:
        assert request_options(record,question,kind)=={}
    assert request_options({'factualReasoningContractVersion':4},'450字以内','paper_comparison')=={}


def test_legacy_profile_does_not_inspect_missing_or_malformed_material_context():
    for version in (None,True,0,1,2,3):
        record={'factualReasoningContractVersion':version,'materialSnapshot':None,'state':None}
        assert request_options(record,'200字以内','paper_comparison')==request_options(
            {'factualReasoningContractVersion':version},'200字以内','paper_comparison')


def test_v5_bounds_extended_comparison_reasoning_without_changing_caps_or_old_requests():
    record={'factualReasoningContractVersion':5,'materialSnapshot':{'materialRefs':['a','b']}}
    flags=request_options(record,'比较两篇，450字以内','paper_comparison')
    old=request_options({**record,'factualReasoningContractVersion':4},'比较两篇，450字以内','paper_comparison')
    new_options=research_model_options('synthesize',flags)
    old_options=research_model_options('synthesize',old)
    assert new_options=={**old_options,'reasoning_effort':'low'}
    assert new_options['max_tokens']==old_options['max_tokens']==8192
    assert research_model_options('repair_claims',{**flags,'_repair_output_limit':4096})==research_model_options(
        'repair_claims',{**old,'_repair_output_limit':4096})
    for kind in ('claim_verification','paper_comparison'):
        assert request_options(record,'200字以内',kind)==request_options(
            {**record,'factualReasoningContractVersion':4},'200字以内',kind)
    for question,kind in [('701字以内','paper_comparison'),('450字以内','claim_verification'),
                          ('450字以内','experiment_design'),('详细比较','paper_comparison')]:
        assert request_options(record,question,kind)=={}


def test_v5_actual_node_still_stops_known_truncation_once_without_fallback():
    from services.deep_research.graph import make_synthesize_node
    record={'factualReasoningContractVersion':5,'question':'比较两篇，450字以内',
            'materialSnapshot':{'materialRefs':['a','b']},'state':{'outputKind':'paper_comparison','evidence':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':'{}','finishReason':'length'})
    assert make_synthesize_node(invoke,update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
    assert invoke.call_count==1
    options=research_model_options('synthesize',invoke.call_args.args[3])
    assert options['reasoning_effort']=='low' and options['max_tokens']==8192


@pytest.mark.parametrize('kind',['claim_verification','paper_comparison'])
def test_v6_only_changes_eligible_short_synthesis_effort_with_identical_output_and_repair_caps(kind):
    old=request_options({'factualReasoningContractVersion':5},'300字以内',kind)
    new=request_options({'factualReasoningContractVersion':6},'300字以内',kind)
    before=research_model_options('synthesize',old);after=research_model_options('synthesize',new)
    assert after=={**before,'reasoning_effort':'low'} and after['max_tokens']==8192
    assert research_model_options('repair_claims',{**new,'_repair_output_limit':4096})==research_model_options(
        'repair_claims',{**old,'_repair_output_limit':4096})
    assert research_model_options('verify',new)==research_model_options('verify',old)
    for question,output in [('详细解释',kind),('301字以内','claim_verification'),
        ('200字以内','direction_survey'),('200字以内','experiment_design')]:
        assert request_options({'factualReasoningContractVersion':6},question,output)=={}


def test_v6_extended_comparison_keeps_the_existing_low_profile():
    record={'materialSnapshot':{'materialRefs':['a','b']}}
    assert request_options({**record,'factualReasoningContractVersion':6},'700字以内','paper_comparison')==request_options(
        {**record,'factualReasoningContractVersion':5},'700字以内','paper_comparison')


def test_v6_reserves_same_tokens_but_fingerprints_a_distinct_request():
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.tools import TrackedLLMInvoker
    provider=Mock();provider.invoke.return_value=LLMResult(content='{}',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False));complete=Mock()
    tracked=TrackedLLMInvoker(provider,reserve,complete,request_options=research_model_options)
    old=request_options({'factualReasoningContractVersion':5},'300字以内','claim_verification')
    new=request_options({'factualReasoningContractVersion':6},'300字以内','claim_verification')
    tracked('r','synthesize','fixed full prompt',old,use_reserve=True)
    fingerprint=reserve.call_args.kwargs['args_digest'];budget=reserve.call_args.kwargs['budget_delta']
    tracked('r','synthesize','fixed full prompt',new,use_reserve=True)
    assert reserve.call_args.kwargs['args_digest']!=fingerprint
    assert reserve.call_args.kwargs['budget_delta']==budget
    assert provider.invoke.call_args.args[0].extra_body['reasoning_effort']=='low'


def test_v6_actual_node_rejects_partial_json_once_without_repair_or_fallback():
    from services.deep_research.graph import make_synthesize_node
    record={'factualReasoningContractVersion':6,'scopeExpressionContractVersion':1,
        'question':'条件和范围，300字以内','state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':'null','rawContent':'{"claims":[{"scopeExpression":', 'finishReason':'length'})
    assert make_synthesize_node(invoke,update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
    assert invoke.call_count==1 and 'reportBody' not in record['state']
    options=research_model_options('synthesize',invoke.call_args.args[3])
    assert options['reasoning_effort']=='low' and options['max_tokens']==8192


def test_v7_only_changes_eligible_initial_compaction_profile_with_same_output_cap():
    from services.deep_research.factual_reasoning import compaction_options,COMPACTION_OPTION
    for version in (None,True,'7',6):
        assert compaction_options({'factualReasoningContractVersion':version},'300字以内','claim_verification')=={}
    record={'factualReasoningContractVersion':7}
    assert compaction_options(record,'301字以内','claim_verification')=={}
    assert compaction_options(record,'300字以内','experiment_design')=={}
    flags=compaction_options(record,'300字以内','claim_verification')
    assert flags=={COMPACTION_OPTION:True}
    before=research_model_options('synthesize_compact',{})
    after=research_model_options('synthesize_compact',flags)
    assert after=={**before,'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    assert after['max_tokens']==8192 and COMPACTION_OPTION not in after
    assert request_options(record,'300字以内','claim_verification')==request_options(
        {'factualReasoningContractVersion':6},'300字以内','claim_verification')


@pytest.mark.parametrize('node,flags',[
    ('synthesize',True),('verify',True),('repair_claims',True),
    ('synthesize_compact',1),('synthesize_compact','true'),('synthesize_compact',None)])
def test_compaction_reasoning_cannot_leak_to_other_nodes_or_accept_non_boolean(node,flags):
    from services.deep_research.factual_reasoning import COMPACTION_OPTION
    with pytest.raises(ValueError):research_model_options(node,{COMPACTION_OPTION:flags})


def test_compaction_profile_is_reserved_before_send_and_does_not_expand_budget():
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.factual_reasoning import COMPACTION_OPTION
    provider=Mock();provider.invoke.return_value=LLMResult(content='{}',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False))
    tracked=TrackedLLMInvoker(provider,reserve,Mock(),request_options=research_model_options)
    tracked('r','synthesize_compact','complete prompt',{})
    old_digest=reserve.call_args.kwargs['args_digest'];old_budget=reserve.call_args.kwargs['budget_delta']
    tracked('r','synthesize_compact','complete prompt',{COMPACTION_OPTION:True})
    assert reserve.call_args.kwargs['args_digest']!=old_digest
    assert reserve.call_args.kwargs['budget_delta']==old_budget
    assert provider.invoke.call_args.args[0].extra_body['thinking']=={'type':'enabled'}
