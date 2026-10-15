from unittest.mock import Mock
import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker


@pytest.mark.parametrize('reported', [None, 'provider-version-label'])
def test_model_labels_survive_durable_settlement_and_reuse_without_new_generation(tmp_path, reported):
    repo = DeepResearchRepository(str(tmp_path/'research.sqlite3'))
    repo.initialize()
    repo.create_run({'runId': 'r', 'taskId': 't', 'question': 'Check mechanism'})
    repo.begin_execution('r')
    client = Mock()
    client.invoke.return_value = LLMResult('fixture', 'configured-alias', 'Answer', LLMUsage(2, 1, 3),
                                         reported_model=reported)
    invoke = TrackedLLMInvoker(client, repo.reserve_call, repo.complete_call)
    result = invoke('r', 'verify', 'Fixed input')
    assert result['model'] == 'configured-alias'
    assert result.get('reportedModel') == reported
    if reported is None:
        assert 'reportedModel' not in result
    restored = DeepResearchRepository(repo.db_path)
    restored.initialize()
    no_send = Mock()
    no_send.invoke.side_effect = AssertionError('Settled call cannot be regenerated')
    replay = TrackedLLMInvoker(no_send, restored.reserve_call, restored.complete_call)
    assert replay('r', 'verify', 'Fixed input') == result
    no_send.invoke.assert_not_called()
    assert len(restored.list_calls('r')) == 1
    assert restored.require_run('r')['budget']['tokens'] == 3
