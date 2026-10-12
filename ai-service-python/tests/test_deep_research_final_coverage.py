import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_verify_node, make_publish_node

TEXT = '相机标定需要已知内参，并固定评测图像划分。'
PLAN = [{'obligations': [{'obligationId': 'o', 'question': '标定所需条件是什么？'}]}]
CLAIMS = [{'claimId': 'c', 'text': TEXT, 'kind': 'reported', 'evidenceRefs': ['e']}]


def verdicts(status='covered'):
    return [{'obligationId': oid, 'status': status,
             'bindings': [{'claimId': 'c', 'excerpt': TEXT}]} for oid in ['o', 'answer_scope']]


def test_audit_checks_final_answer_and_original_question_in_one_reserved_call():
    invoke = Mock(return_value={'content': json.dumps(verdicts())})
    result = audit_final_answer('r', '完整问题', PLAN, CLAIMS, [], invoke, json.loads)
    assert result['status'] == 'checked' and result['gaps'] == []
    invoke.assert_called_once()
    assert invoke.call_args.args[1] == 'verify_answer_coverage'
    assert invoke.call_args.kwargs == {'use_reserve': True}
    assert TEXT in invoke.call_args.args[2] and '完整问题' in invoke.call_args.args[2]


def test_plan_coverage_alone_cannot_hide_omitted_user_requirement():
    invoke = Mock(return_value={'content': json.dumps(verdicts()[:1])})
    result = audit_final_answer('r', '包括预算的新问题', PLAN, CLAIMS, [], invoke, json.loads)
    assert [g['obligationId'] for g in result['gaps']] == ['answer_scope']


@pytest.mark.parametrize('response', [{'content': 'not json'},
    {'content': json.dumps(verdicts()), 'finish_reason': 'length'},
    {'content': json.dumps(verdicts()), 'finishReason': 'length'}, {'content': '{}'}])
def test_invalid_or_truncated_audit_cannot_close_gaps(response):
    result = audit_final_answer('r', 'q', PLAN, CLAIMS, [], Mock(return_value=response), json.loads)
    assert result['status'] == 'invalid_response' and len(result['gaps']) == 2


def test_no_accepted_answer_uses_no_model_call():
    invoke = Mock()
    result = audit_final_answer('r', 'q', PLAN, [], [], invoke, json.loads)
    invoke.assert_not_called()
    assert len(result['gaps']) == 2


def test_distinct_excerpts_from_same_unique_claim_can_support_one_obligation():
    rows = verdicts()
    rows[0]['bindings'].append({'claimId': 'c', 'excerpt': '并固定评测图像划分。'})
    result = audit_final_answer('r', 'q', PLAN, CLAIMS, [],
        Mock(return_value={'content': json.dumps(rows)}), json.loads)
    assert result['gaps'] == []


def test_budget_exhaustion_keeps_gaps_without_retry():
    invoke = Mock(side_effect=BudgetExhaustedError('tokens', 100, 100))
    result = audit_final_answer('r', 'q', PLAN, CLAIMS, [], invoke, json.loads)
    invoke.assert_called_once()
    assert result['status'] == 'budget_exhausted' and len(result['gaps']) == 2


def test_unknown_model_outcome_propagates_without_retry():
    invoke = Mock(side_effect=DeepResearchError('call_unknown', 'unknown'))
    with pytest.raises(DeepResearchError):
        audit_final_answer('r', 'q', PLAN, CLAIMS, [], invoke, json.loads)
    invoke.assert_called_once()


def test_verified_but_incomplete_answer_is_published_as_partial():
    record = {'question': '标定的条件和预算是什么？', 'state': {
        'plan': deepcopy(PLAN), 'reportBody': {'claims': deepcopy(CLAIMS)},
        'evidence': [], 'outputKind': 'claim_verification', 'gaps': []}}
    def update(run_id, fn, **kwargs):
        nonlocal record
        record = fn(record)
        return record
    semantic = Mock()
    invoke = Mock(return_value={'content': json.dumps(verdicts('partial'))})
    node = make_verify_node(lambda c, e, check: {'accepted': c, 'rejected': []}, semantic, update, invoke)
    node({'run_id': 'r'})
    verified = record['state']['verifiedReport']
    assert verified['verifiedClaims'] == CLAIMS
    assert len(verified['answerCoverage']['gaps']) == 2
    publish = Mock(return_value=({'publicationId': 'pub'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r', 'report_version_id': 'v', 'execution_epoch': 0})
    assert result['outcome'] == 'partial'
    assert publish.call_args.kwargs['payload']['claims'] == CLAIMS
    assert publish.call_args.kwargs['payload']['gaps'][0]['stage'] == 'answer'
