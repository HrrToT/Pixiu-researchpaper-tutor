from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests

from llm.response_observation import OPTION
from llm.provider import LLMProviderError
from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import options_for_record
from services.deep_research.shared_experiment_observation import MARKER,enabled,NODES
from services.deep_research.shared_experiment_generation import NODE,prepare
from test_deep_research_shared_experiment_generation import context,response


@pytest.mark.parametrize('value',[None,0,False,True,2,'1'])
def test_observation_requires_its_own_strict_frozen_policy(value):
    r,_,_=context();r[MARKER]=value
    assert not enabled(r,NODE)


def test_receipt_option_changes_identity_but_not_scientific_payload_or_limits():
    from llm.responses_transport import payload
    r,data,aliases=context()
    def save(value):r['state']['sharedExperimentGeneration']=deepcopy(value)
    prepare(r,data,aliases,invoke=Mock(return_value=response()),checkpoint=save)
    old=deepcopy(r);r[MARKER]=1
    for node in NODES:
        args={'max_tokens':6144,'timeout_seconds':90,'temperature':0.0}
        before=request_identity(old,node,'Exact unchanged input',args)
        after=request_identity(r,node,'Exact unchanged input',args)
        assert after['extra']=={**before['extra'],OPTION:True}
        assert before['messages']==after['messages'] and before['prompt']==after['prompt']
        assert payload(before['messages'],before['extra'],model='fixture',temperature=0)==payload(after['messages'],after['extra'],model='fixture',temperature=0)
    for node in ('plan','synthesize','verify_answer_coverage'):
        assert not enabled(r,node)
        with pytest.raises(ValueError):options_for_record(r,node,{OPTION:True})
    with pytest.raises(ValueError):options_for_record(old,NODE,{OPTION:True})


def test_existing_saved_generation_cannot_enable_receipts_and_resend():
    r,data,aliases=context();sent=Mock(return_value=response())
    def save(value):r['state']['sharedExperimentGeneration']=deepcopy(value)
    prepare(r,data,aliases,invoke=sent,checkpoint=save);r[MARKER]=1
    with pytest.raises(DeepResearchError):prepare(r,data,aliases,invoke=sent,checkpoint=save)
    assert sent.call_count==1


@pytest.mark.parametrize('scenario',['success','connect_timeout','body_timeout'])
def test_actual_scoped_ledger_keeps_safe_phases_without_retry(tmp_path,monkeypatch,scenario):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response as http_response
    r,data,aliases=context();r[MARKER]=1
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    http=http_response(response()['content']);http.headers={'x-request-id':'shared-receipt','Authorization':'do-not-save'}
    if scenario=='body_timeout':http.json.side_effect=requests.ReadTimeout('do-not-save URL')
    post=Mock(side_effect=requests.ConnectTimeout('do-not-save proxy')) if scenario=='connect_timeout' else Mock(return_value=http)
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    client=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    tracked=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    def run():
        return prepare(repo.require_run('r'),data,aliases,
            invoke=lambda node,prompt,opts:tracked('r',node,prompt,opts,use_reserve=True),
            checkpoint=lambda value:repo.update_run('r',lambda r:{**r,'state':{**r['state'],'sharedExperimentGeneration':deepcopy(value)}}))
    if scenario=='success':
        value=run();assert run()==value
        observation=repo.list_calls('r')[0]['result']['providerObservation']
        assert observation['bodyReceived'] and observation['requestId']=='shared-receipt'
    else:
        with pytest.raises(LLMProviderError):run()
        call=deepcopy(repo.list_calls('r')[0]);assert call['status']=='unknown' and not call['settled']
        observation=call['error']['providerObservation']
        assert observation['headersReceived'] is (scenario=='body_timeout')
        assert not observation['bodyReceived']
        with pytest.raises(DeepResearchError):run()
        assert repo.list_calls('r')[0]==call
    assert 'do-not-save' not in json.dumps(observation)
    assert post.call_count==1 and post.call_args.kwargs['stream'] is True
    assert post.call_args.kwargs['json']['stream'] is False and OPTION not in post.call_args.kwargs['json']


@pytest.mark.parametrize('replacement',[None,True,False,1,2,'1'])
def test_server_owned_default_policy_cannot_be_injected_or_changed(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **k:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'Design 2x2',MARKER:replacement},start_async=False)
        assert r[MARKER]==0
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,MARKER:replacement})
    finally:facade.shutdown()
