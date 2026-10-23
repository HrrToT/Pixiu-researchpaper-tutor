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
                  [model_failure(402), model_failure(503)]]:
        assert 'HTTP 402' not in _execution_failure_message(calls, False)
