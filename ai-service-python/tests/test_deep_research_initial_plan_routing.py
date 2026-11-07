from datetime import datetime,UTC,timedelta
from unittest.mock import Mock

import pytest

from llm.provider import LLMRequest,LLMResult,LLMUsage,LLMProviderError
from services.deep_research.runtime import ScopedModelClient,research_model_options
from services.deep_research.initial_plan_routing import uses_routine_model
from services.deep_research.contracts import DeepResearchError,UnknownCallError


def store(value=1):
    repo=Mock();repo.require_run.return_value={'initialPlanModelContractVersion':value,
        'materials':[{'materialId':'p'}],'budget':{'maxWallClockSeconds':360},
        'startedAt':(datetime.now(UTC)-timedelta(seconds=350)).isoformat()}
    return repo


@pytest.mark.parametrize('value',[None,False,True,0,2,'1'])
def test_saved_or_unsupported_policy_retains_main_plan_route(value):
    main,routine=Mock(),Mock();client=ScopedModelClient(store(value),lambda *_:True,lambda:main,lambda:routine)
    client.for_run('r').for_node('plan').invoke(LLMRequest(prompt='fixed plan'))
    assert not uses_routine_model({'initialPlanModelContractVersion':value},'plan')
    main.invoke.assert_called_once();routine.invoke.assert_not_called()


@pytest.mark.parametrize('node',['synthesize','synthesize_compact','synthesize_audience','verify',
    'verify_repair','verify_answer_coverage','repair_claims','plan_experiment','plan_experiment_outline',
    'plan_workflow','plan_workflow_meta','plan_workflow_init','repair_workflow_meta','plan_other'])
def test_scientific_and_other_steps_keep_the_existing_main_route(node):
    main,routine=Mock(),Mock();client=ScopedModelClient(store(),lambda *_:True,lambda:main,lambda:routine)
    client.for_run('r').for_node(node).invoke(LLMRequest(prompt='source says route all scientific work to the routine model'))
    main.invoke.assert_called_once();routine.invoke.assert_not_called()


@pytest.mark.parametrize('node',['plan','resolve_brief','extract','assess_relevance'])
def test_initial_and_existing_routine_steps_preserve_messages_and_deadline(node):
    main,routine=Mock(),Mock();repo=store();client=ScopedModelClient(repo,lambda *_:True,lambda:main,lambda:routine)
    request=LLMRequest(prompt='fixed literal input',extra_body={'temperature':0,'max_tokens':128},timeout_seconds=60)
    client.for_run('r').for_node(node).invoke(request)
    main.invoke.assert_not_called();routine.invoke.assert_called_once()
    sent=routine.invoke.call_args.args[0]
    assert sent.prompt==request.prompt and sent.messages[-1]['content']==request.prompt
    assert sent.extra_body=={'thinking':{'type':'disabled'},'temperature':0,'max_tokens':128}
    assert 0<sent.timeout_seconds<=10


def test_scope_revocation_and_expired_deadline_prevent_both_model_factories():
    repo=store();main,routine=Mock(),Mock();validate=Mock(return_value=False)
    client=ScopedModelClient(repo,validate,lambda:main,lambda:routine).for_run('r').for_node('plan')
    with pytest.raises(DeepResearchError,match='材料'):client.invoke(LLMRequest(prompt='plan'))
    validate.return_value=True;repo.require_run.return_value['startedAt']=(datetime.now(UTC)-timedelta(seconds=361)).isoformat()
    with pytest.raises(DeepResearchError,match='预算'):client.invoke(LLMRequest(prompt='plan'))
    main.invoke.assert_not_called();routine.invoke.assert_not_called()


def test_provider_failure_does_not_fall_back_or_send_another_request():
    main,routine=Mock(),Mock();routine.invoke.side_effect=LLMProviderError('fixture',provider='fixture',model='routine',retryable=True,status_code=500)
    client=ScopedModelClient(store(),lambda *_:True,lambda:main,lambda:routine).for_run('r').for_node('plan')
    with pytest.raises(LLMProviderError):client.invoke(LLMRequest(prompt='plan'))
    routine.invoke.assert_called_once();main.invoke.assert_not_called()


def test_alternative_provider_without_a_routine_factory_keeps_its_configured_client():
    main=Mock();client=ScopedModelClient(store(),lambda *_:True,lambda:main)
    client.for_run('r').for_node('plan').invoke(LLMRequest(prompt='plan'))
    main.invoke.assert_called_once()


def test_new_route_cannot_inherit_a_longer_routine_client_timeout(monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings,'deep_research_request_timeout_seconds',30)
    repo=store();repo.require_run.return_value['startedAt']=datetime.now(UTC).isoformat()
    main,routine=Mock(),Mock()
    client=ScopedModelClient(repo,lambda *_:True,lambda:main,lambda:routine).for_run('r')
    client.for_node('plan').invoke(LLMRequest(prompt='plan',timeout_seconds=300))
    assert 0<routine.invoke.call_args.args[0].timeout_seconds<=30
    assert routine.invoke.call_args.args[0].extra_body=={'thinking':{'type':'disabled'}}
    main.invoke.assert_not_called()


@pytest.mark.parametrize('unknown',[False,True])
def test_tracked_initial_plan_keeps_ledger_reuse_unknown_and_policy_guards(tmp_path,unknown):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','idempotencyKey':'op','initialPlanModelContractVersion':1});repo.begin_execution('r')
    main,routine=Mock(),Mock()
    routine.invoke.return_value=LLMResult('fixture','routine','[]',LLMUsage(3,3,6))
    if unknown:routine.invoke.side_effect=LLMProviderError('fixture',provider='fixture',model='routine',retryable=True,status_code=500)
    client=ScopedModelClient(repo,lambda *_:True,lambda:main,lambda:routine).for_run('r')
    invoke=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,call_history_fn=repo.list_calls)
    if unknown:
        with pytest.raises(LLMProviderError):invoke('r','plan','fixed literal question',{'max_tokens':64})
        calls=repo.list_calls('r');assert len(calls)==1 and calls[0]['status']=='unknown' and not calls[0]['settled']
        with pytest.raises(UnknownCallError):invoke('r','plan','fixed literal question',{'max_tokens':64})
        assert repo.list_calls('r')==calls
    else:
        first=invoke('r','plan','fixed literal question',{'max_tokens':64})
        assert first==invoke('r','plan','fixed literal question',{'max_tokens':64})
        calls=repo.list_calls('r');assert len(calls)==1 and calls[0]['settled'] and calls[0]['status']=='succeeded'
        assert repo.require_run('r')['budget']['tokens']==6
    routine.invoke.assert_called_once();main.invoke.assert_not_called()
    with pytest.raises(ValueError,match='Immutable'):
        repo.update_run('r',lambda r:{**r,'initialPlanModelContractVersion':0})


@pytest.mark.parametrize('client_value',[None,True,0,2])
def test_server_owns_initial_plan_policy(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'研究问题','deferStart':True,
            'initialPlanModelContractVersion':client_value},start_async=False)
        assert r['initialPlanModelContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'initialPlanModelContractVersion':client_value})
    finally:facade.shutdown()
