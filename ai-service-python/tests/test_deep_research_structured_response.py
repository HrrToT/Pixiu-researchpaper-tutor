import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.graph import _safe_parse_json
from services.deep_research.tools import BudgetedSemanticChecker


@pytest.mark.parametrize('wrapper', ['```json\n{body}\n```', '```json\n{body}```', '```{body}```', '{body}'])
def test_complete_verdict_array_remains_an_array_with_inline_or_line_fences(wrapper):
    verdicts = [{'claimId': 'a', 'status': 'passed'}, {'claimId': 'b', 'status': 'failed'}]
    assert _safe_parse_json(wrapper.format(body=json.dumps(verdicts))) == verdicts


@pytest.mark.parametrize('body', ['[{"claimId":"a","status":"passed"}',
    '```json\n[{"claimId":"a","status":"passed"}]',
    'prefix [{"claimId":"a","status":"passed"}',
    '[{"claimId":"a","status":"passed"}] [{"claimId":"b","status":"passed"}]'])
def test_incomplete_or_multiple_roots_never_promote_an_inner_verdict(body):
    assert _safe_parse_json(body) == {}


def test_inline_fenced_verdict_is_checked_without_another_provider_request():
    invoke = Mock(return_value={'content': '```json\n[{"claimId":"a","status":"passed"}]```'})
    checker = BudgetedSemanticChecker(invoke, 'r')
    assert checker([{'claimId': 'a', 'evidenceRefs': []}], [])[0]['status'] == 'passed'
    invoke.assert_called_once()
    # Valid JSON syntax does not waive target completeness or truncation.
    invoke.reset_mock()
    with pytest.raises(DeepResearchError, match='未完整返回'):
        checker([{'claimId': 'a', 'evidenceRefs': []}, {'claimId': 'b', 'evidenceRefs': []}], [])
    invoke.assert_called_once()
