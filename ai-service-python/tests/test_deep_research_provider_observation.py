"""Receipts never change payload, completion verdicts, deadlines or replay rules."""
from copy import deepcopy
from threading import Event
from unittest.mock import Mock
import time

import pytest
import requests

from llm.response_observation import OPTION, Observation, sanitize
from llm.provider import LLMProviderError, LLMRequest
from llm.client import DeepSeekLLM
from services.deep_research.workflow_initialization_observation import MARKER, enabled
from services.deep_research.workflow_units import INIT
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import options_for_record
from services.deep_research.contracts import DeepResearchError,UnknownCallError,UnresolvedUnknownError
import test_deep_research_initialization_readable as readable_tests
import test_deep_research_initialization_semantics as semantics_tests
from test_deep_research_schema_transport import response


def record():return {**readable_tests.record(),MARKER:1}


@pytest.mark.parametrize('value',[None,False,True,0,2,'1'])
def test_receipt_marker_is_strict(value):
    r=record();r[MARKER]=value;assert not enabled(r)


def test_receipts_require_the_complete_readable_profile():
    r=record();assert enabled(r);r.pop(readable_tests.MARKER);assert not enabled(r)


def test_generation_json_messages_and_budget_do_not_change():
    from llm.responses_transport import payload
    r=record();old=deepcopy(r);old.pop(MARKER);args={'_workflow_init_target':'baseline','temperature':0.0}
    before=request_identity(old,INIT,'Exact source',args);after=request_identity(r,INIT,'Exact source',args)
    assert after['messages']==before['messages'] and after['prompt']==before['prompt']
    assert after['extra']=={**before['extra'],OPTION:True}
    assert payload(after['messages'],after['extra'],model='fixture',temperature=0)==payload(before['messages'],before['extra'],model='fixture',temperature=0)
    for node in ('plan_workflow_meta','repair_workflow_meta','synthesize'):
        with pytest.raises(ValueError):options_for_record(r,node,{OPTION:True})
    with pytest.raises(ValueError):options_for_record(old,INIT,{**args,OPTION:True})
    with pytest.raises(ValueError):options_for_record(r,INIT,{**args,OPTION:False})


def test_receipt_sanitizer_drops_arbitrary_headers_and_unbounded_or_url_ids():
    value={'version':1,'headersReceived':True,'bodyReceived':False,'httpStatus':200,'headersElapsedMs':1,
        'requestId':'https://secret.invalid/key','Authorization':'secret','body':'private','reasoning':'private'}
    clean=sanitize(value)
    assert clean=={'version':1,'headersReceived':True,'bodyReceived':False,'phase':'headers_received','httpStatus':200,'headersElapsedMs':1}
    value['requestId']='x'*129;assert 'requestId' not in sanitize(value)
    value['version']=True;assert sanitize(value) is None


def request(observe=True):
    r=record()
    if not observe:r.pop(MARKER)
    req=request_identity(r,INIT,'Exact source',{'_workflow_init_target':'baseline','temperature':0.0})
    return LLMRequest(prompt=req['prompt'],messages=req['messages'],extra_body=req['extra'],timeout_seconds=90)


def test_success_records_safe_headers_and_body_but_legacy_stays_exact(monkeypatch):
    http=response('{}');http.headers={'x-request-id':'req-fixture','authorization':'never save'}
    post=Mock(return_value=http);monkeypatch.setattr('llm.client.requests.post',post)
    client=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    result=client.invoke(request())
    assert result.provider_observation['requestId']=='req-fixture' and result.provider_observation['bodyReceived']
    assert 'authorization' not in result.provider_observation and post.call_args.kwargs['stream'] is True
    http.close.assert_called_once();body=post.call_args.kwargs['json']
    assert body['stream'] is False and OPTION not in body
    old=client.invoke(request(False))
    assert old.provider_observation is None and post.call_args.kwargs['json']==body
    assert 'stream' not in post.call_args.kwargs


@pytest.mark.parametrize('kind',['read','connect','http','bad_json'])
def test_failure_receipts_do_not_change_provider_failure_classification(monkeypatch,kind):
    http=response('{}');http.headers={'x-ds-request-id':'request-fixture'}
    if kind=='read':http.json.side_effect=requests.ReadTimeout('private URL')
    elif kind=='http':http.status_code=402
    elif kind=='bad_json':http.json.side_effect=ValueError('private body')
    post=Mock(side_effect=requests.ConnectTimeout('private proxy')) if kind=='connect' else Mock(return_value=http)
    monkeypatch.setattr('llm.client.requests.post',post)
    with pytest.raises(LLMProviderError) as caught:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid').invoke(request())
    error=caught.value;obs=error.provider_observation
    assert 'private' not in str(error) and 'private' not in str(obs)
    assert obs['headersReceived']==(kind!='connect')
    assert obs['bodyReceived']==(kind=='bad_json')
    assert error.status_code==(402 if kind=='http' else None)
    if kind!='connect':http.close.assert_called_once()


def test_absolute_deadline_freezes_receipt_and_discards_late_body(monkeypatch):
    release,headers,closed=Event(),Event(),Event();http=response('{}')
    http.headers={'x-request-id':'request-early'};http.close.side_effect=closed.set
    def body():
        headers.set();assert release.wait(2);return response('{}').json()
    http.json.side_effect=body;post=Mock(return_value=http);monkeypatch.setattr('llm.client.requests.post',post)
    client=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid',timeout_seconds=.05)
    started=time.monotonic()
    try:
        with pytest.raises(LLMProviderError) as caught:client.invoke(request())
        assert time.monotonic()-started<.8 and headers.is_set()
        saved=deepcopy(caught.value.provider_observation)
        assert caught.value.failure_kind=='deadline_exceeded' and saved['httpStatus']==200 and not saved['bodyReceived']
    finally:release.set()
    assert closed.wait(1) and caught.value.provider_observation==saved
    post.assert_called_once()


def test_freeze_does_not_wait_on_slow_header_mapping():
    release,entered,done=Event(),Event(),Event();obs=Observation()
    class Headers:
        def get(self,_):entered.set();assert release.wait(2);return 'late-request-id'
    from threading import Thread
    def worker():
        try:obs.headers(Mock(status_code=200,headers=Headers()))
        finally:done.set()
    Thread(target=worker,daemon=True).start();assert entered.wait(1)
    try:
        started=time.monotonic()
        snapshot=obs.freeze();assert snapshot['headersReceived'] and 'requestId' not in snapshot
        assert time.monotonic()-started<1
    finally:release.set()
    assert done.wait(1) and obs.freeze()==snapshot


def test_complete_workflow_and_reopen_keep_one_receipt_policy():
    r,invoke,run=semantics_tests.setup();r.update({readable_tests.reasoning_tests.MARKER:1,readable_tests.MARKER:1,MARKER:1})
    saved=run();assert saved['status']=='ready' and saved['request']['initializationObservationContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT:assert call.args[2][OPTION] is True
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_existing_readable_requests_cannot_enable_receipts_and_resend():
    r,invoke,run=semantics_tests.setup();r.update({readable_tests.reasoning_tests.MARKER:1,readable_tests.MARKER:1})
    run();count=invoke.call_count;r[MARKER]=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('scenario',['success','read_timeout','absolute_deadline','budget'])
def test_ledger_preserves_receipt_unknown_and_no_duplicate_send(tmp_path,monkeypatch,scenario):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import BudgetExhaustedError
    r=record();r.update(runId='r',taskId='t');repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    http=response('{}');http.headers={'x-request-id':'req-ledger'}
    release,closed=Event(),Event();http.close.side_effect=closed.set
    if scenario=='read_timeout':http.json.side_effect=requests.ReadTimeout('private request')
    if scenario=='absolute_deadline':
        def delayed_body():
            assert release.wait(2);return response('{}').json()
        http.json.side_effect=delayed_body
    post=Mock(return_value=http);monkeypatch.setattr('llm.client.requests.post',post)
    client=ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid',
        timeout_seconds=.1 if scenario=='absolute_deadline' else 90)).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario=='budget' else repo.reserve_call
    invoke=TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    def run():return invoke('r',INIT,'Exact source',{'_workflow_init_target':'baseline','temperature':0.0},use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario in ('read_timeout','absolute_deadline'):
        try:
            with pytest.raises(LLMProviderError):run()
        finally:release.set()
        assert closed.wait(1)
        call=repo.list_calls('r')[0];snapshot=deepcopy(call)
        assert call['status']=='unknown' and call['error']['providerObservation']['requestId']=='req-ledger'
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
        assert repo.list_calls('r')[0]==snapshot
    else:
        result=run();assert result['providerObservation']['bodyReceived'] and run()==result
    post.assert_called_once()


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_server_owns_receipt_marker_and_rejects_mutation(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,MARKER:replacement},start_async=False)
        assert r[MARKER]==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda old:{**old,MARKER:replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(MARKER);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda item:{**item,MARKER:1})
    finally:facade.shutdown()
