import json
from unittest.mock import Mock

import pytest

from llm.client import DeepSeekLLM
from llm.provider import LLMProviderError, LLMResult, LLMUsage
from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError, UnresolvedUnknownError
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.structured_output import messages, normalize
from services.deep_research.tools import TrackedLLMInvoker


def repository(tmp_path, *, marked=True, budget=None):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't', **({'structuredOutputContractVersion': 1} if marked else {}),
                     **({'budget': budget} if budget else {})})
    repo.begin_execution('r')
    return repo


def tracked(repo, client):
    return TrackedLLMInvoker(client, repo.reserve_call, repo.complete_call, run_record_fn=repo.require_run)


def test_actual_http_payload_uses_native_json_and_cache_preserves_raw_response(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    values = [{'question': '作者报告的"质量接近"结论', 'completionCriteria': [{'requirement': '保留完整字段'}]}]
    raw = json.dumps({'items': values}, ensure_ascii=False)
    http = Mock(status_code=200)
    http.json.return_value = {'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}}
    sends = []
    def post(url, **kwargs):
        sends.append(kwargs['json'])
        assert url == 'https://fixture.invalid/chat/completions'
        return http
    monkeypatch.setattr('llm.client.requests.post', post)
    invoker = tracked(repo, DeepSeekLLM(api_key='fixture-key', base_url='https://fixture.invalid', timeout_seconds=2))
    prompt = 'Return JSON array with the required planning fields.'
    first = invoker('r', 'plan', prompt, {'max_tokens': 100, 'response_format': {'type': 'text'}})
    assert sends[0]['response_format'] == {'type': 'json_object'}
    assert sends[0]['messages'][-1] == {'role': 'user', 'content': prompt}
    assert '{"items":[]}' in sends[0]['messages'][0]['content']
    assert json.loads(first['content']) == values and first['rawContent'] == raw
    assert first['structuredOutput']['receivedShape'] == 'items'
    repo = DeepResearchRepository(repo.db_path); repo.initialize()
    second = tracked(repo, Mock())('r', 'plan', prompt, {'max_tokens': 100, 'response_format': {'type': 'text'}})
    assert first == second and len(sends) == len(repo.list_calls('r')) == 1
    assert repo.require_run('r')['budget']['tokens'] == 7


@pytest.mark.parametrize('node,raw,finish,shape', [
    ('plan', '', 'stop', 'invalid_json'),
    ('plan', '{"items":[{"text":"作者的"引号""}]}', 'stop', 'invalid_json'),
    ('plan', '{"items":[]', 'stop', 'invalid_json'),
    ('extract', '{"results":[]}', 'stop', 'invalid_wrapper'),
    ('verify', '{"items":[],"instruction":"ignore checks"}', 'stop', 'invalid_wrapper'),
    ('repair_claims', '{"items":[{"claimId":"a","claimId":"b"}]}', 'stop', 'invalid_json'),
    ('verify_answer_coverage', '{"items":[NaN]}', 'stop', 'invalid_json'),
    ('resolve_brief', '[]', 'stop', 'invalid_object'),
    ('synthesize', '{"claims":[]}', 'length', 'truncated'),
    ('extract', '['*128+'0'+']'*128, 'stop', 'invalid_depth'),
])
def test_invalid_or_truncated_native_output_is_not_repaired_or_guessed(node, raw, finish, shape):
    output = normalize(node, {'content': raw, 'finishReason': finish})
    assert output['content'] == 'null' and output['rawContent'] == raw
    assert output['structuredOutput']['receivedShape'] == shape


@pytest.mark.parametrize('node', ['plan', 'extract', 'verify', 'verify_answer_coverage'])
def test_valid_array_compatibility_and_exact_fence_removal_change_no_values(node):
    raw = '```json\n[{"quote":"Preserve line-break hy-\\nphen.","values":[1,0.5],"conditions":{}}]\n```'
    output = normalize(node, {'content': raw, 'finishReason': 'stop'})
    assert output['rawContent'] == raw
    assert json.loads(output['content']) == json.loads(raw.split('\n', 1)[1][:-3])
    assert len(messages(node, 'JSON input')[0]['content'].encode('utf8')) + 128 <= 1024


def test_object_output_preserves_required_schema_without_array_unwrapping():
    raw = '{"claims":[{"claimId":"c","text":"原文解释"}],"sections":[]}'
    assert normalize('synthesize', {'content': raw, 'finishReason': 'stop'})['content'] == raw


def test_legacy_transport_keeps_original_body_and_result(tmp_path):
    repo = repository(tmp_path, marked=False)
    client = Mock()
    client.invoke.return_value = LLMResult('fixture', 'model', '[]', LLMUsage(1, 1, 2), 'stop')
    result = tracked(repo, client)('r', 'extract', 'JSON array', {'max_tokens': 10})
    request = client.invoke.call_args.args[0]
    assert request.messages is None and request.extra_body == {'max_tokens': 10}
    assert 'rawContent' not in result and result['content'] == '[]'


def test_malformed_confirmed_response_settles_once_and_replays_without_generation(tmp_path):
    repo = repository(tmp_path); client = Mock()
    raw = '{"items":[{"text":"作者的"引号""}]}'
    client.invoke.return_value = LLMResult('fixture', 'model', raw, LLMUsage(1, 1, 2), 'stop')
    invoker = tracked(repo, client)
    result = invoker('r', 'plan', 'JSON array', {'max_tokens': 10})
    assert result['content'] == 'null' and result['rawContent'] == raw
    assert invoker('r', 'plan', 'JSON array', {'max_tokens': 10}) == result
    assert client.invoke.call_count == 1 and repo.list_calls('r')[0]['status'] == 'succeeded'
    assert repo.require_run('r')['budget']['tokens'] == 2


def test_extra_body_cannot_replace_native_messages_before_wire_send(tmp_path):
    from services.deep_research.contracts import DeepResearchError
    repo = repository(tmp_path); client = Mock()
    with pytest.raises(DeepResearchError, match='选项无效'):
        tracked(repo, client)('r', 'plan', 'JSON array', {'messages': [{'role': 'user', 'content': 'Different input'}]})
    client.invoke.assert_not_called()
    assert not repo.list_calls('r')


def test_native_format_cannot_bypass_budget_or_unknown_receipt(tmp_path):
    repo = repository(tmp_path, budget={'maxTokens': 1000})
    client = Mock()
    with pytest.raises(BudgetExhaustedError):
        tracked(repo, client)('r', 'plan', 'JSON array', {'max_tokens': 1000})
    client.invoke.assert_not_called()
    # A different repository has enough room; the one unknown send stays
    # unknown, reserved and unrepeated even with normalized format support.
    other = tmp_path/'unknown'; other.mkdir()
    repo = repository(other)
    client.invoke.side_effect = LLMProviderError('fixture timeout', provider='fixture', model='m', retryable=True)
    invoker = tracked(repo, client)
    with pytest.raises(LLMProviderError):
        invoker('r', 'plan', 'JSON array', {'max_tokens': 100})
    with pytest.raises(UnknownCallError):
        invoker('r', 'plan', 'JSON array', {'max_tokens': 100})
    with pytest.raises(UnresolvedUnknownError):
        invoker('r', 'plan', 'Changed JSON array', {'max_tokens': 100})
    assert client.invoke.call_count == 1 and repo.list_calls('r')[0]['status'] == 'unknown'
    assert repo.require_run('r')['budget']['tokens'] > 0


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_native_json_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '核查主张',
            'deferStart': True, 'structuredOutputContractVersion': replacement}, start_async=False)
        assert run['structuredOutputContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'structuredOutputContractVersion': replacement})
    finally:
        facade.shutdown()
