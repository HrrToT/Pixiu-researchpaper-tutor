import json
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.structured_output import (
    ARRAY_NODES, PRIVATE_LITERAL_POLICY, PRIVATE_SHARED_POLICY, messages, normalize,
)
from test_deep_research_structured_output import repository, tracked


def test_private_numeric_policy_fits_reserved_framing_and_preserves_user_input():
    prompt = 'Original evidence and complete required blueprint'
    wire = messages('plan_experiment', prompt, 13)
    assert wire[-1] == {'role': 'user', 'content': prompt}
    assert wire[0]['content'] == PRIVATE_LITERAL_POLICY
    assert len(PRIVATE_LITERAL_POLICY.encode('utf8')) + 128 <= 1024
    assert 'no bare arithmetic (2^16, 2**16, 1/2)' in PRIVATE_LITERAL_POLICY
    assert messages('plan_experiment', prompt, 12)[0]['content'] == PRIVATE_SHARED_POLICY
    for node in ARRAY_NODES | {'synthesize', 'synthesize_compact', 'synthesize_audience'}:
        assert messages(node, prompt, 13, prospective=True) == messages(node, prompt, 12, prospective=True)


@pytest.mark.parametrize('expression', ['2^16', '2**16', '1/2'])
def test_invalid_numeric_response_stays_raw_and_rejected_without_evaluation(expression):
    raw = '{"shape":[' + expression + ',8]}'
    response = normalize('plan_experiment', {'content': raw, 'finishReason': 'stop'})
    assert response['rawContent'] == raw
    assert response['content'] == 'null'
    assert response['structuredOutput']['receivedShape'] == 'invalid_json'


def test_valid_literal_shape_is_preserved_in_settled_cached_response(tmp_path):
    repo = repository(tmp_path, version=13)
    raw = '{"shape":[65536,8],"initializer":"proposal, not source fact"}'
    client = Mock()
    client.invoke.return_value = LLMResult(content=raw, provider='fixture', model='m',
        usage=LLMUsage(input_tokens=5, output_tokens=2, total_tokens=7), finish_reason='stop')
    invoke = tracked(repo, client)
    first = invoke('r', 'plan_experiment', 'Complete source context', {'max_tokens': 100})
    assert json.loads(first['content'])['shape'] == [65536, 8]
    assert first['rawContent'] == raw
    assert invoke('r', 'plan_experiment', 'Complete source context', {'max_tokens': 100}) == first
    assert client.invoke.call_count == 1
    assert repo.require_run('r')['budget']['tokens'] == 7
