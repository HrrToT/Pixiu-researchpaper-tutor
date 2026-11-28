"""Server-owned planning reasoning; no retries or relaxation of response checks."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.experiment_planning import request_identity,prepare_plan
from services.deep_research.experiment_envelope import DIRECT_PLAN_OPTION
from services.deep_research.planning_transport import options_for_record,descriptor
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_experiment_capacity import current


def request(record,node='plan_experiment'):
    return request_identity(record,node,'Exact original evidence',{'max_tokens':6144,'temperature':0,
        **({DIRECT_PLAN_OPTION:True} if node=='plan_experiment' else {})})


def test_planning_reasoning_changes_only_the_versioned_role_options():
    old=current();old['structuredOutputContractVersion']=15
    new={**old,'experimentPlanningReasoningContractVersion':1}
    before=request(old);after=request(new)
    assert before['prompt']==after['prompt'] and before['messages']==after['messages']
    expected=deepcopy(before);expected['extra'].update(thinking={'type':'enabled'},reasoning_effort='low')
    assert after==expected and before['extra']['thinking']=={'type':'disabled'}
    assert after['extra']['max_tokens']==6144 and after['extra']['response_format']==descriptor()
    for node in ('synthesize','verify','plan_workflow_meta','plan_workflow_init'):
        assert request(old,node)==request(new,node)


@pytest.mark.parametrize('value',[None,True,'1',0,2,1.0])
def test_unmarked_or_unsupported_policy_does_not_rewrite_old_requests(value):
    old=current();old['structuredOutputContractVersion']=15
    assert request({**old,'experimentPlanningReasoningContractVersion':value})==request(old)


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_policy_is_server_owned_and_immutable(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'policy.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'Design',
            'experimentPlanningReasoningContractVersion':replacement,'deferStart':True},start_async=False)
        assert row['experimentPlanningReasoningContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(row['runId'],lambda r:{**r,'experimentPlanningReasoningContractVersion':replacement})
    finally:facade.shutdown()


def test_legacy_record_cannot_acquire_policy_on_resume(tmp_path):
    repo=DeepResearchRepository(tmp_path/'legacy.sqlite3');repo.initialize()
    r=current();r.update(runId='r',taskId='t');r.pop('experimentPlanningReasoningContractVersion',None)
    repo.create_run(r)
    with pytest.raises(ValueError,match='Immutable'):
        repo.update_run('r',lambda r:{**r,'experimentPlanningReasoningContractVersion':1})
    assert 'experimentPlanningReasoningContractVersion' not in repo.require_run('r')


@pytest.mark.parametrize('scenario',['success','unknown'])
def test_actual_http_policy_identity_settlement_and_unknown_dedup(tmp_path,monkeypatch,scenario):
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from services.deep_research.contracts import UnknownCallError,UnresolvedUnknownError
    from test_deep_research_schema_transport import response
    import requests
    r=current();r.update(runId='r',taskId='t',structuredOutputContractVersion=15,
        experimentPlanningReasoningContractVersion=1)
    repo=DeepResearchRepository(tmp_path/'wire.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('fixture unknown')) if scenario=='unknown' else Mock(return_value=response())
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    invoke=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,
        request_options=research_model_options,run_record_fn=repo.require_run)
    options={'max_tokens':6144,'temperature':0,DIRECT_PLAN_OPTION:True}
    def send():return invoke('r','plan_experiment','Exact original evidence',options,use_reserve=True)
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):send()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):send()
        assert repo.list_calls('r')[0]['status']=='unknown'
    else:
        first=send();assert send()==first and repo.list_calls('r')[0]['status']=='succeeded'
        assert repo.require_run('r')['budget']['tokens']==16
    assert post.call_count==1
    wire=post.call_args.kwargs['json']
    assert wire['reasoning']['effort']=='low' and wire['max_output_tokens']==6144
    assert wire['text']['format']==descriptor()
    assert repo.list_calls('r')[0]['argsDigest']==digest(request(r))


def test_invalid_json_is_retained_once_and_new_policy_cannot_change_frozen_request():
    r=current();r.update(structuredOutputContractVersion=15,experimentPlanningReasoningContractVersion=1)
    invoke=Mock(return_value={'content':'null','rawContent':'{"protocol":{}},"unresolved":[]',
        'finishReason':'stop'})
    def checkpoint(v):r['state']['experimentPlanning']=deepcopy(v)
    def run():return prepare_plan(r,prompt='Exact original evidence',aliases={},invoke=invoke,parse=json.loads,checkpoint=checkpoint)
    for _ in range(2):
        with pytest.raises(DeepResearchError) as e:run()
        assert e.value.code=='invalid_experiment_planning_response'
    assert invoke.call_count==1 and r['state']['experimentPlanning']['status']=='invalid_response'
    del r['experimentPlanningReasoningContractVersion']
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_experiment_planning_state' and invoke.call_count==1
