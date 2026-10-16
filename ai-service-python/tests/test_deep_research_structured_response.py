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
    '```json\n[{"claimId":"a","status":"passed"}',
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


@pytest.mark.parametrize('wrapper', ['```json\n{body}', '```\n{body}', '```json{body}'])
@pytest.mark.parametrize('value', [[{'claimId': 'a', 'status': 'failed', 'reason': 'Missing initial values.'}],
                                  {'claims': [], 'sections': []}])
def test_missing_markdown_terminator_preserves_the_entire_complete_json_value(wrapper, value):
    assert _safe_parse_json(wrapper.format(body=json.dumps(value))) == value


@pytest.mark.parametrize('body', ['```json\n[{"claimId":"a"}] trailing prose',
    '```json\n[{"claimId":"a"}] [{"claimId":"b"}]',
    '```json\n[{"claimId":"a"}]``', '```json\n[{"claimId":"a"}'])
def test_unclosed_fence_never_salvages_a_substring_or_repairs_json(body):
    assert _safe_parse_json(body) == {}


def test_complete_json_without_fence_terminator_still_needs_all_verdicts_and_untruncated_transport():
    response = {'content': '```json\n[{"claimId":"a","status":"failed","reason":"Missing initial values."}]'}
    invoke = Mock(return_value=response)
    checker = BudgetedSemanticChecker(invoke, 'r')
    assert checker([{'claimId': 'a', 'evidenceRefs': []}], [])[0]['status'] == 'failed'
    invoke.assert_called_once()
    invoke.reset_mock()
    with pytest.raises(DeepResearchError, match='未完整返回'):
        checker([{'claimId': 'a', 'evidenceRefs': []}, {'claimId': 'b', 'evidenceRefs': []}], [])
    invoke.assert_called_once()
    invoke.reset_mock()
    invoke.return_value = {**response, 'finishReason': 'length'}
    with pytest.raises(DeepResearchError, match='未完整返回'):
        checker([{'claimId': 'a', 'evidenceRefs': []}], [])
    invoke.assert_called_once()
