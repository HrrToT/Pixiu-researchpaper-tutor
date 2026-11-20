"""Reasoning changes only one new-run role and its frozen request identity."""
from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.workflow_revision_reasoning import enabled
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import dispatch_options,overhead_bytes
from services.deep_research.contracts import BudgetExhaustedError,digest,UnknownCallError,UnresolvedUnknownError
from test_deep_research_workflow_revision_input import record as previous

NODE='repair_workflow_meta'


def record():return {**previous(),'workflowRevisionReasoningContractVersion':1}


@pytest.mark.parametrize('value',[None,True,False,0,2,'1'])
def test_strict_immutable_profile_marker(value):
    assert not enabled({**record(),'workflowRevisionReasoningContractVersion':value})


@pytest.mark.parametrize('key',['workflowRevisionInputContractVersion','workflowMetadataEnvelopeContractVersion',
 'workflowMetadataOutputContractVersion','workflowMetadataRepairContractVersion','executionWorkflowContractVersion','structuredOutputContractVersion'])
def test_partial_profiles_cannot_change_reasoning(key):
    assert not enabled({**record(),key:0})


def test_same_prompt_messages_schema_deadline_and_output_reservation_only_role_changes():
    r=record();old=previous();before=deepcopy(old)
    a=request_identity(r,NODE,'same complete source and feedback',{'temperature':0})
    b=request_identity(old,NODE,'same complete source and feedback',{'temperature':0})
    assert a['prompt']==b['prompt'] and a['messages']==b['messages']
    assert a['extra']['thinking']=={'type':'enabled'} and a['extra']['reasoning_effort']=='low'
    assert b['extra']['thinking']=={'type':'disabled'} and b['extra']['reasoning_effort']=='none'
    clean=lambda e:{k:v for k,v in e.items() if k not in ('thinking','reasoning_effort')}
    assert clean(a['extra'])==clean(b['extra'])
    assert a['extra']['max_tokens']==6144 and a['extra']['timeout_seconds']==90
    assert digest(a)!=digest(b) and old==before
    for node in ('plan_workflow_meta','plan_workflow_init','plan_experiment','synthesize'):
        assert request_identity(r,node,'same',{})==request_identity(old,node,'same',{})


def test_pending_legacy_revision_cannot_be_repurposed_with_reasoning():
    from test_deep_research_workflow_revision_input import failed,sized_source,StopBeforeProvider
    from services.deep_research.workflow_metadata_repair import prepare
    from services.deep_research.contracts import DeepResearchError
    r=previous();w,u=failed();source,aliases=sized_source(r,w,38117);saved=[]
    invoke=Mock(side_effect=StopBeforeProvider())
    with pytest.raises(StopBeforeProvider):
        prepare(r,source_data=source,failed=u,aliases=aliases,existing=None,invoke=invoke,checkpoint=saved.append)
    frozen=deepcopy(saved[-1]);r['workflowRevisionReasoningContractVersion']=1
    with pytest.raises(DeepResearchError,match='身份或状态已改变'):
        prepare(r,source_data=source,failed=u,aliases=aliases,existing=saved[-1],invoke=invoke,checkpoint=saved.append)
    assert saved[-1]==frozen and invoke.call_count==1


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_http_payload_usage_reservation_and_unknown_dedup(tmp_path,monkeypatch,scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r=record();r.update(runId='r',taskId='t')
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('unknown')) if scenario=='unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post',post)
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario=='budget' else Mock(wraps=repo.reserve_call)
    invoke=TrackedLLMInvoker(scoped,reserve,repo.complete_call,request_options=research_model_options,
      run_record_fn=repo.require_run,experiment_max_input_bytes=32000,workflow_revision_max_input_bytes=40000)
    req=request_identity(r,NODE,'same complete source',{'temperature':0})
    def run():return invoke('r',NODE,req['prompt'],dispatch_options(r,NODE,req['extra']),use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    else:
        result=run();assert result['content']=='{}' and result['usage']['total_tokens']==16
        assert 'not answer' not in result['content']
    assert post.call_count==1 and repo.list_calls('r')[0]['argsDigest']==digest(req)
    sent=post.call_args.kwargs['json']
    assert sent['reasoning']=={'effort':'low'} and sent['max_output_tokens']==6144
    assert post.call_args.kwargs['timeout']==90
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(req['prompt'].encode())+1024+overhead_bytes(r,NODE)+6144


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_server_owned_and_old_rows_cannot_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
          'workflowRevisionReasoningContractVersion':replacement},start_async=False)
        assert r['workflowRevisionReasoningContractVersion']==0 and not enabled(r)
        assert request_identity(r,NODE,'same',{})['extra']['thinking']=={'type':'disabled'}
        # A historical server-issued version1 record still has its exact policy
        # and cannot be rewritten, even though new runs now freeze disabled.
        r={**r,'runId':'historical-v1','idempotencyKey':'historical-v1','workflowRevisionReasoningContractVersion':1}
        repo.create_run(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowRevisionReasoningContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('workflowRevisionReasoningContractVersion');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowRevisionReasoningContractVersion':1})
    finally:facade.shutdown()
