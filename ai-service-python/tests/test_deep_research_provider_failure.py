from services.deep_research.facade import _execution_failure_message


def model_failure(status):
    return {'tool': 'llm_invoke', 'status': 'failed',
            'error': {'type': 'provider_error', 'status_code': status,
                      'message': 'Private provider diagnostic must not be displayed'}}


def test_confirmed_payment_rejection_is_actionable_without_leaking_raw_diagnostics():
    message = _execution_failure_message([model_failure(402)], False)
    assert 'HTTP 402' in message and '额度与计费状态' in message
    assert 'Private provider' not in message


def test_unknown_call_remains_paused_even_if_another_call_has_payment_error():
    message = _execution_failure_message([model_failure(402), {'status': 'unknown'}], True)
    assert '结果尚未确认' in message
    assert 'HTTP 402' not in message
    assert '不会自动重发' in message
    assert '再发起' not in message


def test_unrelated_or_stale_payment_failure_does_not_mislabel_current_failure():
    for calls in [[], [model_failure(503)], [dict(model_failure(402), tool='discovery')],
                  [model_failure(402), model_failure(503)],
                  [model_failure(402),{'tool':'llm_invoke','status':'succeeded'}],
                  [model_failure(402),{'tool':'retrieve','status':'failed'}]]:
        assert 'HTTP 402' not in _execution_failure_message(calls, False)


def test_payment_failure_stops_once_and_preserves_generated_work_across_reload(tmp_path):
    from copy import deepcopy
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from test_deep_research_end_to_end import FixtureModel,make_facade,create
    class PaymentRejected(FixtureModel):
        failures=0
        def invoke(self,request):
            if request.prompt.startswith(('Verify these claims','Check the complete factual assertions')):
                self.requests.append(request);self.failures+=1
                raise LLMProviderError('Private billing diagnostic',provider='deepseek',model='fixture',
                    status_code=402,retryable=False)
            return super().invoke(request)
    model=PaymentRejected();repo,facade,_=make_facade(tmp_path,model)
    try:
        record=create(facade);rid=record['runId'];repo.begin_execution(rid)
        facade._execute_graph(rid)
        saved=repo.require_run(rid);calls=repo.list_calls(rid)
        assert saved['status']=='failed' and saved['errorCode']=='provider_payment_rejected' and model.failures==1
        assert saved['state']['evidence'] and saved['state']['reportBody']['claims']
        assert calls[-1]['status']=='failed' and calls[-1]['error']['status_code']==402
        assert not any(c['status'] in ('pending','unknown') for c in calls)
        result=facade.get(rid)
        assert '额度与计费状态' in result['error'] and 'Private billing diagnostic' not in result['error']
        assert not repo.list_outbox(rid)
        body=deepcopy(saved['state']['reportBody']);sources=deepcopy(saved['state']['evidence'])
        count=len(model.requests);restored=DeepResearchRepository(repo.db_path);restored.recover()
        assert restored.require_run(rid)['status']=='failed'
        assert restored.require_run(rid)['state']['reportBody']==body
        assert restored.require_run(rid)['state']['evidence']==sources
        facade.get(rid);facade.get(rid)
        assert len(model.requests)==count and model.failures==1
    finally:facade.shutdown()
