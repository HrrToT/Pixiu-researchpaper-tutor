from copy import deepcopy
import json
import re

import pytest

from services.deep_research.comparison_capacity import before_synthesis
from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.comparison_joint_reports import resource_allocation_enabled


def budget(ordinary=2, reserved=1, maximum=18):
    return {'budget': {'maxModelCalls': maximum, 'modelCalls': ordinary,
                       'reservedModelCalls': reserved}}


def test_allocation_counts_both_spent_pools_and_reserves_generation_audit_repair():
    value = budget(); before = deepcopy(value)
    result = before_synthesis(value)
    assert result['maxDraftPoints'] == 12 and result['remainingModelCalls'] == 15
    assert result['generationAuditAndRepairCalls'] == 3
    assert not result['scientificApproval'] and not result['tokensAndTimeFitEstablished']
    assert before_synthesis(budget(maximum=100))['maxDraftPoints'] == 24
    assert value == before


@pytest.mark.parametrize('key', ['maxModelCalls', 'modelCalls', 'reservedModelCalls'])
@pytest.mark.parametrize('value', [True, -1, 1.0, None, '2'])
def test_invalid_ledger_is_never_coerced(key, value):
    record = budget(); record['budget'][key] = value
    with pytest.raises(ValueError): before_synthesis(record)


def test_no_room_or_unaffordable_exact_user_count_stops_before_generation():
    with pytest.raises(BudgetExhaustedError): before_synthesis(budget(15, 0))
    with pytest.raises(ValueError): before_synthesis(budget(18, 1))
    with pytest.raises(BudgetExhaustedError):
        before_synthesis(budget(), {'count': 13, 'mode': 'exact'})
    assert before_synthesis(budget(), {'count': 13, 'mode': 'max'})['maxDraftPoints'] == 12
    assert before_synthesis(budget(), {'count': 4, 'mode': 'exact'})['maxDraftPoints'] == 4


@pytest.mark.parametrize('version', [0, 1, True, '2', None])
def test_allocation_is_not_enabled_for_frozen_or_invalid_policy(version):
    from test_deep_research_comparison_intent import record
    r = record(); r.update(comparisonPlanningContractVersion=2,
                           comparisonJointReportsContractVersion=version)
    assert not resource_allocation_enabled(r)


def run_node(version, count, *, ordinary=2, reserved=1):
    from test_deep_research_comparison_joint_reports import fixture
    from test_deep_research_comparison_intent import record
    from services.deep_research.graph import make_synthesize_node
    cp, payload, ev, question = fixture()
    payload['conclusions'] *= count
    current = record()
    current.update(runId='r', question=question, comparisonPlanningContractVersion=2,
                   comparisonJointReportsContractVersion=version)
    current['budget'].update(budget(ordinary, reserved)['budget'])
    current['state'].update(evidence=[ev], outputKind='paper_comparison',
                            plan=[{'itemId':'all', 'question':'comparison', 'obligations':cp['requirements']}])
    sent = []
    def update(rid, fn, **kwargs):
        nonlocal current
        current = fn(deepcopy(current)); return deepcopy(current)
    def invoke(rid, node, prompt, options, **kwargs):
        sent.append(int(re.search(r'Maximum total draft points across cells AND conclusions: (\d+)', prompt)[1]))
        return {'content': json.dumps(payload)}
    node = make_synthesize_node(invoke, update)
    try:
        result = node({'run_id':'r'})
    except BudgetExhaustedError:
        assert not sent
        raise
    return current, sent, result, payload


def test_actual_node_admits_eleven_with_budget_but_never_verifies_them():
    current, sent, result, _ = run_node(2, 11)
    assert sent == [12] and not result.get('error_code')
    assert current['state']['synthesisDraftAdmission']['status'] == 'compiled_unverified'
    assert len(current['state']['reportBody']['claims']) == 11
    assert not current['state'].get('verifiedReport')
    assert not current['state'].get('synthesisRejectedDraft')
    old, sent, result, _ = run_node(1, 11)
    assert sent == [6] and result['error_code'] == 'invalid_synthesis_response'
    assert 'synthesisDraftAdmission' not in old['state']


def test_overflow_is_retained_only_as_unverified_without_second_call_or_report():
    current, sent, result, payload = run_node(2, 13)
    assert sent == [12] and result['error_code'] == 'invalid_synthesis_response'
    state = current['state']
    assert state['synthesisRejectedDraft'] == {
        'verification':'unchecked', 'publishable':False, 'payload':payload}
    assert state['synthesisDraftAdmission']['receivedPoints'] == 13
    assert not state.get('reportBody') and not state.get('verifiedReport')


def test_actual_node_with_no_review_room_never_calls_model():
    with pytest.raises(BudgetExhaustedError): run_node(2, 1, ordinary=15, reserved=0)
