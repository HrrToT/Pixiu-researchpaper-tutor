from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.factual_reasoning import OPTION, request_options
from services.deep_research.runtime import research_model_options


@pytest.mark.parametrize('kind',['claim_verification','paper_comparison'])
def test_only_new_short_factual_answers_choose_reasoning(kind):
    record={'factualReasoningContractVersion':1}
    assert request_options(record,'给出判断，300字以内。',kind)=={OPTION:True}
    for value in [None,True,False,0,3,'1']:
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


@pytest.mark.parametrize('replacement',[None,True,False,0,1,'1'])
def test_policy_is_server_owned_immutable_and_not_client_selected(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'200字以内',
            'deferStart':True,'factualReasoningContractVersion':replacement},start_async=False)
        assert p['factualReasoningContractVersion']==2
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
