"""Reasoning is local to new fixed-prose edits; no budget or recovery shortcuts."""
from copy import deepcopy
import json
from unittest.mock import Mock,patch
import pytest
from services.deep_research.compaction_editor import fixed_scope_profile,fixed_scope_options
from services.deep_research.factual_reasoning import COMPACTION_OPTION
from services.deep_research.runtime import research_model_options
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.contracts import DeepResearchError
from test_deep_research_preferred_scope_edit import options,edit
from test_deep_research_compaction_editing import inputs

KEY='fixedScopeEditorReasoningContractVersion'


def policy(value=1):return {KEY:value,'compactionEditingContractVersion':3,'factualReasoningContractVersion':10}


@pytest.mark.parametrize('value',[None,True,False,'1',0,2])
def test_old_or_untrusted_profile_does_not_change_options(value):
    assert fixed_scope_profile(policy(value),'300字以内','claim_verification')==0
    assert fixed_scope_options(policy(value),'300字以内','claim_verification')=={}


@pytest.mark.parametrize('question,kind',[('500字以内','claim_verification'),('解释','claim_verification'),('300字以内','experiment_design'),('300字以内','direction_survey')])
def test_noneligible_paths_retain_their_existing_profile(question,kind):
    assert fixed_scope_options(policy(),question,kind)=={}


def test_existing_calibrated_profile_retains_original_output_cap():
    options=fixed_scope_options(policy(),'300字以内','claim_verification')
    assert options=={COMPACTION_OPTION:True}
    actual=research_model_options('synthesize_compact',{'max_tokens':2000,'temperature':0.0,**options})
    assert actual['thinking']=={'type':'enabled'} and actual['reasoning_effort']=='low' and actual['max_tokens']==8192
    old=research_model_options('synthesize_compact',{'max_tokens':2000,'temperature':0.0})
    assert old['max_tokens']==actual['max_tokens'] and old['reasoning_effort']=='none'


@pytest.mark.parametrize('phase',['synthesis','repair'])
@pytest.mark.parametrize('profile',[None,True,1])
@pytest.mark.parametrize('limit',[300,500])
def test_actual_graph_dispatches_low_only_for_new_eligible_fixed_editor(phase,profile,limit):
    from services.deep_research.graph import make_synthesize_node,make_verify_node
    from test_deep_research_fixed_scope_compaction import fixture
    report,audits,response=fixture();report['claims'][0]['text']*=3
    record={**policy(profile),'question':f'{limit}字以内','scopeExpressionContractVersion':3,
        'scopeCompactionContractVersion':1,'scopeExpressionReviewContractVersion':2,
        'reportPresentationContractVersion':2,'repairCompactionContractVersion':1,
        'state':{'outputKind':'claim_verification','evidence':[]}}
    initial={'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in report['claims']]}
    if phase=='repair':record['state'].update(reportBody=report,repairReport=report,repairAttempted=True,initialVerification=initial,repairTargets=initial,initialAnswerCoverage={'status':'not_requested','gaps':[]},repairBatchState={'scopeExpressionAudit':{'0':audits}})
    draft=deepcopy(report);draft['claims'][1].update(text='',scopeExpression=audits[0]['expression'])
    joint={'claims':[{'claimId':c['claimId'],'text':'已有简短说明。' if c['claimId']=='f' else '',
        'conditions':{},'scopeExpression':None if c['claimId']=='f' else audits[0]['expression']} for c in report['claims']]}
    requests=[]
    def update(_id,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(_id,node,prompt,options,**kw):
        requests.append((node,prompt,options))
        return {'content':json.dumps(draft if node=='synthesize' else response if 'editableClaims：' in prompt else joint)}
    if phase=='synthesis':
        result=make_synthesize_node(invoke,update)({'run_id':'r'});assert 'error_code' not in result
    else:
        verifier=Mock(side_effect=lambda rows,*_: {'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in rows]})
        with patch('services.deep_research.repair.repair_rejected',return_value=report['claims']):make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
        assert record['state']['verifiedReport']['verifiedClaims']==[]
    compactions=[r for r in requests if r[0]=='synthesize_compact'];assert len(compactions)==1
    actual=research_model_options('synthesize_compact',compactions[0][2])
    assert actual['reasoning_effort']==('low' if type(profile) is int and profile==1 and limit==300 else 'none')


def test_profile_is_in_checkpoint_identity_but_not_editor_prompt_and_known_result_is_reused():
    report,audits,_=inputs();direct=Mock(return_value={'content':json.dumps(edit())});joint=Mock();states=[]
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'100字以内',joint,json.loads)
    old=compact_repairs(*args,invoke_fixed=direct,checkpoint=states.append,selective_fixed_edit=True,**options());prompt=direct.call_args.args[0];old_state=deepcopy(states[-1])
    assert compact_repairs(*args,invoke_fixed=direct,checkpoint=states.append,selective_fixed_edit=True,fixed_editor_profile=0,**options())==old
    assert states[-1]==old_state
    direct.reset_mock()
    with pytest.raises(DeepResearchError,match='输入不一致'):compact_repairs(*args,invoke_fixed=direct,saved=old_state,selective_fixed_edit=True,fixed_editor_profile=1,**options())
    direct.assert_not_called()
    new=[];out=compact_repairs(*args,invoke_fixed=direct,checkpoint=new.append,selective_fixed_edit=True,fixed_editor_profile=1,**options())
    assert out and direct.call_args.args[0]==prompt and new[-1]['inputDigest']!=old_state['inputDigest'];direct.reset_mock()
    assert compact_repairs(*args,invoke_fixed=direct,saved=new[-1],selective_fixed_edit=True,fixed_editor_profile=1,**options())==out
    direct.assert_not_called();joint.assert_not_called()


@pytest.mark.parametrize('profile',[None,True,'1',2])
def test_invalid_checkpoint_profile_rejected_without_dispatch(profile):
    report,audits,_=inputs();invoke=Mock()
    with pytest.raises(ValueError):compact_repairs(report,report['claims'],[],{},'100字以内',invoke,json.loads,fixed_editor_profile=profile)
    invoke.assert_not_called()


def test_new_profile_is_server_owned_immutable_and_absent_from_legacy_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'300字以内',KEY:False},start_async=False)
        assert type(run[KEY]) is int and run[KEY]==1
        old=deepcopy(run);old.pop(KEY);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        for rid,value in ((run['runId'],True),('old',1)):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,KEY:value})
        assert KEY not in repo.require_run('old')
    finally:facade.shutdown()


def test_actual_tracked_request_fingerprints_profile_and_reserves_8192_before_send(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.provider import LLMResult,LLMUsage
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':'300字以内','state':{},'budget':{'maxModelCalls':2,'maxTokens':50000,'maxWallClockSeconds':180,'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r')
    reserve=Mock(wraps=repo.reserve_call);requests=[]
    def answer(request):
        assert reserve.call_count==len(requests)+1
        requests.append(request)
        return LLMResult(provider='fixture',model='fixture',content='{"claims":[]}',usage=LLMUsage(5,5,10),finish_reason='stop')
    client=Mock();client.invoke.side_effect=answer
    invoker=TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,run_record_fn=repo.require_run)
    invoker('r','synthesize_compact','identical prompt',{'max_tokens':2000,'temperature':0.0})
    invoker('r','synthesize_compact','identical prompt',{'max_tokens':2000,'temperature':0.0,**fixed_scope_options(policy(),'300字以内','claim_verification')})
    assert len(requests)==2 and requests[0].extra_body['reasoning_effort']=='none' and requests[1].extra_body['reasoning_effort']=='low'
    assert all(r.extra_body['max_tokens']==8192 for r in requests)
    assert reserve.call_args_list[0].kwargs['args_digest']!=reserve.call_args_list[1].kwargs['args_digest']
    assert all(c.kwargs['budget_delta']['tokens']>=8192 for c in reserve.call_args_list)
    assert all(c['settled'] for c in repo.list_calls('r'))


def test_unknown_low_profile_call_stays_reserved_and_is_not_resent(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.provider import LLMProviderError
    repo=DeepResearchRepository(tmp_path/'unknown.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':'300字以内','state':{},'budget':{'maxModelCalls':2,'maxTokens':50000,'maxWallClockSeconds':180,'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r')
    client=Mock();client.invoke.side_effect=LLMProviderError('fixture timeout',provider='fixture',model='fixture',retryable=True)
    invoker=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,run_record_fn=repo.require_run)
    options={'max_tokens':2000,'temperature':0.0,**fixed_scope_options(policy(),'300字以内','claim_verification')}
    with pytest.raises(LLMProviderError):invoker('r','synthesize_compact','same prompt',options)
    original=deepcopy(repo.list_calls('r'))
    with pytest.raises(DeepResearchError):invoker('r','synthesize_compact','same prompt',options)
    assert repo.list_calls('r')==original and len(original)==1
    assert original[0]['status']=='unknown' and not original[0]['settled']
    client.invoke.assert_called_once()
