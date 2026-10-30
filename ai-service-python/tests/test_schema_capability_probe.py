import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage


spec = importlib.util.spec_from_file_location('schema_probe', Path(__file__).parents[1] /
                                             'scripts/probe_deepseek_schema_capability.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def result(value):
    return LLMResult('fixture', 'fixture', json.dumps(value), LLMUsage(2, 1, 3), 'stop')


def test_receipt_precedes_every_send_and_completed_probe_cannot_repeat(tmp_path):
    values = [{'value': 'allowed'}, {'groups': ['0']}, {'step': {'kind': 'observe', 'groups': ['1']}}]
    def invoke(request):
        name = request.extra_body['response_format']['name'].removeprefix('probe_')
        intent = tmp_path / (name + '.intent.json')
        assert intent.exists() and json.loads(intent.read_text())['prompt'] == request.prompt
        assert request.extra_body['max_tokens'] == 256 and request.timeout_seconds == 30
        return result(values.pop(0))
    sender = Mock(side_effect=invoke)
    summary = probe.run(tmp_path, sender)
    assert len(summary) == sender.call_count == 3 and all(x['satisfiesDiagnosticObligations'] for x in summary)
    with pytest.raises(FileExistsError): probe.run(tmp_path, sender)
    assert sender.call_count == 3


def test_unknown_stops_probe_and_cannot_resend_or_leak_exception(tmp_path):
    sender = Mock(side_effect=TimeoutError('sensitive://credential'))
    with pytest.raises(RuntimeError): probe.run(tmp_path, sender)
    with pytest.raises(FileExistsError): probe.run(tmp_path, sender)
    assert sender.call_count == 1
    assert not (tmp_path / 'single_group.intent.json').exists()
    assert 'credential' not in (tmp_path / 'constant.failure.json').read_text()


def test_schema_violation_is_recorded_without_retry_or_normalization(tmp_path):
    sender = Mock(side_effect=[result({'value': 'forbidden'}), result({'groups': ['0', '1']}),
                               result({'step': {'kind': 'observe', 'groups': ['0', '1']}})])
    summary = probe.run(tmp_path, sender)
    assert not any(x['satisfiesDiagnosticObligations'] for x in summary)
    assert sender.call_count == 3
    assert json.loads((tmp_path / 'single_group.result.json').read_text())['content'] == '{"groups": ["0", "1"]}'
