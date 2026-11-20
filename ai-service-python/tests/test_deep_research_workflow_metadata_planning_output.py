"""More first-pass output is reserved, never used to accept truncation."""
from copy import deepcopy
from datetime import datetime,UTC
from unittest.mock import Mock
import json

import pytest

from services.deep_research.workflow_metadata_planning_output import enabled,NODE
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import dispatch_options,overhead_bytes
from services.deep_research.contracts import digest,DeepResearchError,BudgetExhaustedError,UnknownCallError,UnresolvedUnknownError
from test_deep_research_workflow_metadata_window import record as previous,large_workflow,StopBeforeProvider


def record():return {**previous(),'workflowMetadataPlanningOutputContractVersion':1}


@pytest.mark.parametrize('marker',[None,True,False,0,2,'1'])
def test_profile_marker_is_strict(marker):
    assert not enabled({**record(),'workflowMetadataPlanningOutputContractVersion':marker})


@pytest.mark.parametrize('key',['workflowMetadataInputContractVersion','workflowMetadataEnvelopeContractVersion',
 'workflowPremiseAllocationContractVersion','experimentStageAllocationContractVersion',
 'workflowMetadataRepairContractVersion','structuredOutputContractVersion'])
def test_incomplete_profiles_cannot_get_larger_output(key):
    assert not enabled({**record(),key:0})


def test_only_first_metadata_output_changes_with_same_prompt_schema_and_deadline():
    r=record();old=previous();before=deepcopy(old)
    a=request_identity(r,NODE,'same complete question, plan and evidence',{'temperature':0})
    b=request_identity(old,NODE,'same complete question, plan and evidence',{'temperature':0})
    assert a['prompt']==b['prompt'] and a['messages']==b['messages']
    assert a['extra']['max_tokens']==8192 and b['extra']['max_tokens']==6144
    assert {k:v for k,v in a['extra'].items() if k!='max_tokens'}=={k:v for k,v in b['extra'].items() if k!='max_tokens'}
    assert a['extra']['thinking']=={'type':'disabled'} and a['extra']['timeout_seconds']==90
    assert old==before and digest(a)!=digest(b)
    for node in ('repair_workflow_meta','plan_workflow_init','plan_experiment_outline','synthesize'):
        assert request_identity(r,node,'same',{})==request_identity(old,node,'same',{})


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_wire_reservation_and_unknown_identity_match(tmp_path,monkeypatch,scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r=record();r.update(runId='r',taskId='t');repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('unknown')) if scenario=='unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post',post)
    client=ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario=='budget' else Mock(wraps=repo.reserve_call)
    invoke=TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,
      run_record_fn=repo.require_run,experiment_max_input_bytes=32000,workflow_metadata_max_input_bytes=40000)
    req=request_identity(r,NODE,'same complete source',{'temperature':0})
    def run():return invoke('r',NODE,req['prompt'],dispatch_options(r,NODE,req['extra']),use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    else:run()
    assert post.call_count==1 and repo.list_calls('r')[0]['argsDigest']==digest(req)
    wire=post.call_args.kwargs['json']
    assert wire['max_output_tokens']==8192 and wire['reasoning']=={'effort':'none'}
    assert post.call_args.kwargs['timeout']==90
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(req['prompt'].encode())+1024+overhead_bytes(r,NODE)+8192


@pytest.mark.parametrize('used_tokens',[26277,70000])
def test_real_repository_reservation_still_enforces_original_total_budget(tmp_path,used_tokens):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.provider import LLMResult,LLMUsage
    r=record();r.update(runId='r',taskId='t',startedAt=datetime.now(UTC).isoformat())
    r['budget']={'profile':'standard','maxModelCalls':18,'maxTokens':100000,'maxWallClockSeconds':360,
      'reserveModelCalls':5,'reserveTokens':50000,'finalizationBudgetVersion':1,'releasedReserveTokens':0,
      'modelCalls':5,'reservedModelCalls':1,'tokens':used_tokens,'normalTokens':17584,'elapsedSeconds':70,
      'maxExternalSearches':6,'maxFulltextFetches':6,'externalSearches':0,'fulltextFetches':0}
    original=deepcopy(r['budget']);repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    client=Mock();client.invoke.return_value=LLMResult(content='{}',provider='fixture',model='offline',usage=LLMUsage(11,5,16))
    invoke=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run,
      experiment_max_input_bytes=32000,workflow_metadata_max_input_bytes=40000)
    text='x'*(34891-overhead_bytes(r,NODE))
    if used_tokens==70000:
        with pytest.raises(BudgetExhaustedError):invoke('r',NODE,text,{'max_tokens':8192},use_reserve=True)
        assert repo.list_calls('r')==[] and repo.require_run('r')['budget']['tokens']==70000
        client.invoke.assert_not_called();return
    invoke('r',NODE,text,{'max_tokens':8192},use_reserve=True)
    call=repo.list_calls('r')[0];budget=repo.require_run('r')['budget']
    assert call['reservedTokens']==34891+1024+8192 and budget['tokens']==used_tokens+16
    assert all(budget[k]==original[k] for k in ('maxModelCalls','maxTokens','maxWallClockSeconds','reserveModelCalls','reserveTokens'))


@pytest.mark.parametrize('kind',['truncated','oversize'])
def test_larger_allowance_keeps_truncation_and_byte_rejections(kind):
    from test_deep_research_workflow_metadata_edits import fixture
    from services.deep_research.execution_workflow_blueprint import packed
    r,invoke,run=large_workflow();r['workflowMetadataPlanningOutputContractVersion']=1
    wire=fixture()[0];wire['sourceRefs']=['E1']
    if kind=='oversize':wire['unresolved']=['x'*33000]
    raw='{' if kind=='truncated' else packed(wire)
    invoke.side_effect=None;invoke.return_value={'content':raw,'finishReason':'length' if kind=='truncated' else 'stop'}
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    unit=r['state']['executionWorkflowBlueprint']['units']['metadata']
    assert invoke.call_count==1 and unit['request']['extra']['max_tokens']==8192
    assert ('unit.output_truncated' if kind=='truncated' else 'unit.output_capacity') in unit['errors']


def test_pending_old_request_cannot_be_upgraded_or_resent():
    r,invoke,run=large_workflow()
    with pytest.raises(StopBeforeProvider):run()
    before=deepcopy(r['state']['executionWorkflowBlueprint']);r['workflowMetadataPlanningOutputContractVersion']=1
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_blueprint_state' and invoke.call_count==1
    assert r['state']['executionWorkflowBlueprint']==before


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_server_owned_and_old_rows_cannot_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
          'workflowMetadataPlanningOutputContractVersion':replacement},start_async=False)
        assert r['workflowMetadataPlanningOutputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowMetadataPlanningOutputContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('workflowMetadataPlanningOutputContractVersion');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowMetadataPlanningOutputContractVersion':1})
    finally:facade.shutdown()
