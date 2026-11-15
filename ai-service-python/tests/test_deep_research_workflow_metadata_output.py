from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.workflow_metadata_output import enabled
from services.deep_research.experiment_planning import request_identity
from services.deep_research.contracts import DeepResearchError,BudgetExhaustedError
from services.deep_research.workflow_units import META
from test_deep_research_workflow_metadata_repair import setup_repair,response
from test_deep_research_workflow_metadata_symbols import pair
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers


def record():
    r,_,_,_=setup_repair([])
    r.update(workflowMetadataRepairContractVersion=34,structuredOutputContractVersion=15,
             workflowMetadataOutputContractVersion=1)
    return r


@pytest.mark.parametrize('version',[None,True,False,0,2,'1'])
def test_exact_server_marker_required(version):
    assert not enabled({**record(),'workflowMetadataOutputContractVersion':version})


@pytest.mark.parametrize('node',[META,'repair_workflow_meta'])
def test_full_output_allowance_frozen_before_identity_and_old_requests_unchanged(node):
    r=record();before=deepcopy(r);legacy=deepcopy(r);legacy.pop('workflowMetadataOutputContractVersion')
    old=request_identity(legacy,node,'Unmodified source input',{'temperature':0})
    new=request_identity(r,node,'Unmodified source input',{'temperature':0})
    assert old['extra']['max_tokens']==2048 and new['extra']['max_tokens']==6144
    assert new['extra']['timeout_seconds']==90 and new['extra']['thinking']=={'type':'disabled'}
    assert old['prompt']==new['prompt'] and old['messages']==new['messages']
    assert old['extra']['response_format']==new['extra']['response_format'] and r==before


def test_other_roles_and_earlier_metadata_versions_keep_their_exact_options():
    r=record();old=deepcopy(r);old.pop('workflowMetadataOutputContractVersion')
    for node in ('plan_experiment_outline','synthesize','verify','plan_workflow_init'):
        extra={'temperature':0}
        if node=='plan_workflow_init':
            from services.deep_research.workflow_initialization_wire import TARGET_OPTION,enabled as wire_enabled
            if wire_enabled(r):extra[TARGET_OPTION]='component'
        assert request_identity(r,node,'Same source',extra)==request_identity(old,node,'Same source',extra)
    r['workflowMetadataRepairContractVersion']=33;old['workflowMetadataRepairContractVersion']=33
    assert request_identity(r,META,'Same source',{})==request_identity(old,META,'Same source',{})


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_wire_reservation_and_unknown_identity_match(tmp_path,monkeypatch,scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.planning_transport import overhead_bytes,dispatch_options
    from services.deep_research.contracts import UnknownCallError,UnresolvedUnknownError,digest
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response as wire_response
    r=record();r.update(runId='r',taskId='t')
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('unknown')) if scenario=='unknown' else Mock(return_value=wire_response('{}'))
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',99999,100000)) if scenario=='budget' else Mock(wraps=repo.reserve_call)
    invoke=TrackedLLMInvoker(scoped,reserve,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    req=request_identity(r,META,'Exact original full request',{'temperature':0})
    def run():return invoke('r',META,req['prompt'],dispatch_options(r,META,req['extra']),use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    else:run()
    assert post.call_count==1
    call=repo.list_calls('r')[0]
    assert call['argsDigest']==digest(req)
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(req['prompt'].encode())+1024+overhead_bytes(r,META)+6144
    assert post.call_args.kwargs['json']['max_output_tokens']==6144


@pytest.mark.parametrize('invalid',['truncated','oversize'])
def test_allowance_never_approves_truncated_or_oversize_metadata(invalid):
    _,good=pair()
    if invalid=='oversize':good['unresolved']=['X'*9000]
    first=response(good)
    if invalid=='truncated':first['finishReason']='length'
    r,_,invoke,run=setup_repair([first]);r.update(workflowMetadataRepairContractVersion=34,
        structuredOutputContractVersion=15,workflowMetadataOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError) as e:run()
        assert e.value.code=='invalid_workflow_unit_response'
    assert invoke.call_count==1
    unit=r['state']['executionWorkflowBlueprint']['units']['metadata']
    assert unit['response']==first and unit['request']['extra']['max_tokens']==6144
    assert ('unit.output_truncated' if invalid=='truncated' else 'unit.output_capacity') in unit['errors']


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_server_owned_and_old_runs_cannot_opt_in(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
            'workflowMetadataOutputContractVersion':replacement},start_async=False)
        assert enabled(r) and r['workflowMetadataOutputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowMetadataOutputContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');del old['workflowMetadataOutputContractVersion'];repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowMetadataOutputContractVersion':1})
    finally:facade.shutdown()
