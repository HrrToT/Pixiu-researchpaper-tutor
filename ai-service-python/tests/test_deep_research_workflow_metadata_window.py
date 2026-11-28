"""Complete metadata admission is bounded and never clips mandatory premises."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.workflow_metadata_window import enabled,input_limit,NODE
from services.deep_research.workflow_premises import allocate
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.planning_transport import overhead_bytes
from services.deep_research.experiment_planning import request_identity
from services.deep_research.contracts import DeepResearchError,BudgetExhaustedError
from test_deep_research_workflow_premises import record as premise_record,workflow_setup
from test_deep_research_metadata_envelope import record as output_record


def profile(r):
    r.update({k:v for k,v in output_record().items() if k.endswith('ContractVersion')})
    r['workflowMetadataInputContractVersion']=1
    return r


def record():return profile(premise_record())


@pytest.mark.parametrize('marker',[None,True,False,0,2,'1'])
def test_marker_is_strict_and_old_records_keep_32kb(marker):
    r={**record(),'workflowMetadataInputContractVersion':marker}
    assert not enabled(r) and input_limit(r,NODE)==32000


@pytest.mark.parametrize('key',['workflowMetadataEnvelopeContractVersion','workflowMetadataOutputContractVersion',
 'workflowMetadataRepairContractVersion','executionWorkflowContractVersion','structuredOutputContractVersion',
 'workflowPremiseAllocationContractVersion','experimentStageAllocationContractVersion'])
def test_incomplete_profiles_cannot_expand_input(key):
    assert not enabled({**record(),key:0})


def test_only_metadata_input_changes_not_request_options_or_other_roles():
    r=record();old=deepcopy(r);old.pop('workflowMetadataInputContractVersion')
    assert enabled(r) and input_limit(r,NODE)==40000
    for node in (NODE,'plan_workflow_init','repair_workflow_meta','synthesize','plan_experiment_outline'):
        assert request_identity(r,node,'same source',{})==request_identity(old,node,'same source',{})
        if node!=NODE:assert input_limit(r,node)==32000


def test_all_18_required_rows_and_full_question_remain_whole_in_larger_window():
    r=record();ids=[f'E{i}' for i in range(1,19)]
    r['state']['synthesisPremiseAllocation']={'requiredPremiseEvidenceAliases':ids[:16]}
    rows=[{'evidenceId':eid,'quote':eid+' exact required quote '+'x'*1400} for eid in ids]
    source={'question':'Complete 2x2, shared initialization, all metrics and interaction effects',
      'requirements':['all four arms'],'unverifiedScientificPlan':{'sourceRefs':ids[16:],'protocol':{'all':'retained'}},
      'sources':{'P1':'owned fixed version'},'tables':{'T1':{'all':[1,False,None]}},'evidence':rows}
    aliases={i:i for i in ids};context={'allowedSourceRefs':ids}
    render=lambda data,ctx:data+json.dumps(ctx,separators=(',',':'))
    args=dict(source_data=json.dumps(source),context=context,aliases=aliases,prior_values=[],node=NODE,render=render)
    body,selected,ctx,allowed,audit=allocate(r,**args)
    assert 32000<audit['inputBytes']<=40000 and audit['maxInputBytes']==40000
    assert json.loads(selected)==source and set(allowed)==set(ids) and ctx['allowedSourceRefs']==sorted(ids)
    assert audit['requiredAliases']==ids and audit['suppliedAliases']==ids
    old=deepcopy(r);old.pop('workflowMetadataInputContractVersion')
    _,old_data,_,_,old_audit=allocate(old,**args)
    assert json.loads(old_data)==source and old_audit['inputBytes']>old_audit['maxInputBytes']==32000


class StopBeforeProvider(Exception):pass


def large_workflow(*,new=True):
    r,invoke,run=workflow_setup(optional=True,all_required=True)
    profile(r)
    if not new:r.pop('workflowMetadataInputContractVersion')
    invoke.side_effect=StopBeforeProvider()
    return r,invoke,run


def test_actual_builder_admits_complete_large_metadata_before_any_output():
    r,invoke,run=large_workflow()
    with pytest.raises(StopBeforeProvider):run()
    unit=r['state']['executionWorkflowBlueprint']['units']['metadata']
    assert unit['status']=='pending' and invoke.call_count==1 and invoke.call_args.args[0]==NODE
    assert unit['premiseAllocation']['requiredAliases']==['E1','E2','E3']
    assert unit['premiseAllocation']['suppliedAliases']==['E1','E2','E3']
    assert 32000<unit['premiseAllocation']['inputBytes']<=40000


def test_legacy_refusal_cannot_be_reinterpreted_after_marker_mutation():
    r,invoke,run=large_workflow(new=False)
    with pytest.raises(DeepResearchError):run()
    before=deepcopy(r['state']['executionWorkflowBlueprint'])
    assert before['units']['metadata']['status']=='not_started_capacity'
    r['workflowMetadataInputContractVersion']=1
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_blueprint_state'
    assert r['state']['executionWorkflowBlueprint']==before
    invoke.assert_not_called()


@pytest.mark.parametrize('configured',[24000,32000,40000])
def test_actual_invoker_honors_server_limit_and_whole_budget_before_http(configured):
    r=record();reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000));client=Mock()
    call=TrackedLLMInvoker(client,reserve,Mock(),run_record_fn=lambda _:r,
      experiment_max_input_bytes=32000,workflow_metadata_max_input_bytes=configured)
    assert call.prompt_byte_limit('r',NODE)==configured and call.prompt_byte_limit('r','plan_workflow_init')==32000
    n=configured-overhead_bytes(r,NODE)
    with pytest.raises(BudgetExhaustedError):call('r',NODE,'x'*n,{'max_tokens':6144})
    assert reserve.call_args.kwargs['budget_delta']['tokens']==configured+1024+6144
    with pytest.raises(ValueError,match='Prompt too large'):call('r',NODE,'x'*(n+1),{'max_tokens':6144})
    assert reserve.call_count==1
    client.invoke.assert_not_called()


@pytest.mark.parametrize('cap',[True,0,40001,'40000',40000.0])
def test_bad_metadata_server_limits_rejected(cap):
    with pytest.raises(ValueError,match='workflow metadata'):
        TrackedLLMInvoker(Mock(),Mock(),Mock(),workflow_metadata_max_input_bytes=cap)


def test_legacy_ignores_new_configured_window():
    r=record();r.pop('workflowMetadataInputContractVersion')
    call=TrackedLLMInvoker(Mock(),Mock(),Mock(),run_record_fn=lambda _:r,
      experiment_max_input_bytes=32000,workflow_metadata_max_input_bytes=40000)
    assert call.prompt_byte_limit('r',NODE)==32000


@pytest.mark.parametrize('used_tokens',[28528,70000])
def test_actual_repository_reservation_keeps_full_case_budget_unchanged(tmp_path,used_tokens):
    from datetime import datetime,UTC
    from services.deep_research.repository import DeepResearchRepository
    from llm.provider import LLMResult,LLMUsage
    r=record();r.update(runId='r',taskId='t',startedAt=datetime.now(UTC).isoformat())
    r['budget']={'profile':'standard','maxModelCalls':18,'maxTokens':100000,'maxWallClockSeconds':360,
      'reserveModelCalls':5,'reserveTokens':50000,'finalizationBudgetVersion':1,'releasedReserveTokens':0,
      'modelCalls':6,'reservedModelCalls':1,'tokens':used_tokens,'normalTokens':19064,'elapsedSeconds':73,
      'maxExternalSearches':6,'maxFulltextFetches':6,'externalSearches':0,'fulltextFetches':0}
    before=deepcopy(r['budget']);repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    client=Mock();client.invoke.return_value=LLMResult(content='{}',provider='fixture',model='offline',usage=LLMUsage(11,5,16))
    call=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run,
       experiment_max_input_bytes=32000,workflow_metadata_max_input_bytes=40000)
    text='x'*(33667-overhead_bytes(r,NODE))
    if used_tokens==70000:
        with pytest.raises(BudgetExhaustedError):call('r',NODE,text,{'max_tokens':6144},use_reserve=True)
        assert repo.list_calls('r')==[] and repo.require_run('r')['budget']['tokens']==used_tokens
        client.invoke.assert_not_called();return
    call('r',NODE,text,{'max_tokens':6144},use_reserve=True)
    ledger=repo.list_calls('r')[0];budget=repo.require_run('r')['budget']
    assert ledger['reservedTokens']==33667+1024+6144 and ledger['settled']==1
    assert budget['tokens']==used_tokens+16 and budget['normalTokens']==19064
    assert budget['reservedModelCalls']==2 and client.invoke.call_count==1
    assert all(budget[k]==before[k] for k in ('maxModelCalls','maxTokens','maxWallClockSeconds','reserveModelCalls','reserveTokens'))


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_server_owned_and_old_runs_cannot_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','outputKind':'experiment_design','deferStart':True,
          'workflowMetadataInputContractVersion':replacement},start_async=False)
        assert r['workflowMetadataInputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowMetadataInputContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('workflowMetadataInputContractVersion');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowMetadataInputContractVersion':1})
    finally:facade.shutdown()
