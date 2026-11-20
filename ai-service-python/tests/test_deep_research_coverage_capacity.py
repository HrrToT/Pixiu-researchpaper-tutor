import json
from copy import deepcopy
from unittest.mock import Mock

from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.finalization_pool import select_reservation_pool


def long_contract():
    return [{'obligations': [{'obligationId': f'o{i}', 'question': f'Explain requirement {i}.',
        'completionCriteria': [{'criterionId': f'c{j}', 'requirement': f'Explain relationship {j}.',
                                'responseType': 'explanation'} for j in range(3)]} for i in range(6)]}]


def answers():
    return [{'claimId': f'c{i}', 'text': 'Full accepted answer content ' + str(i),
             'kind': 'reported', 'evidenceRefs': [f'e{i}']} for i in range(9)]


def test_long_contract_gets_one_larger_bounded_audit_without_dropping_any_requirement_or_answer():
    plan, claims = long_contract(), answers()
    before = deepcopy((plan, claims))
    def invoke(run, node, prompt, options, **kwargs):
        assert 3500 < options['max_tokens'] <= 8192
        assert all(o['obligationId'] in prompt for o in plan[0]['obligations'])
        assert all(c['text'] in prompt for c in claims)
        assert 'answer_scope' in prompt
        return {'content': '[]', 'finishReason': 'stop'}
    call = Mock(side_effect=invoke)
    result = audit_final_answer('r', 'Whole original user question', plan, claims, [], call, json.loads)
    call.assert_called_once()
    assert len(result['gaps']) == 7  # Output capacity never confers completion.
    assert (plan, claims) == before


def test_long_audit_fits_the_actual_fallback_pool_and_preserves_complete_selected_quotes():
    budget = {'maxTokens': 100000, 'tokens': 62990, 'reserveTokens': 50000,
              'normalTokens': 25804, 'maxModelCalls': 18, 'modelCalls': 8,
              'reserveModelCalls': 5, 'reservedModelCalls': 5}
    evidence = [{'evidenceId': f'e{i}', 'quote': f'whole source passage {i} ' + 'x' * 2500,
                 'sourceWorkId': f'p{i}', 'conditions': {}} for i in range(12)]
    original = deepcopy((budget, evidence))
    def invoke(run, node, prompt, options, **kwargs):
        delta = {'modelCalls': 1, 'tokens': len(prompt.encode()) + 1024 + options['max_tokens']}
        assert delta['tokens'] <= 24196
        assert select_reservation_pool(budget, delta, True, node) is False
        rows = json.loads(prompt.split('Available evidence for detecting omitted conditions: ')[1].split('\n\nFactual')[0])
        assert 0 < len(rows) < len(evidence)
        assert all(row['quote'] in {e['quote'] for e in evidence} for row in rows)
        return {'content': '[]'}
    call = Mock(side_effect=invoke)
    audit_final_answer('r', 'Whole original question', long_contract(), answers(), evidence, call, json.loads, budget=budget)
    call.assert_called_once()
    assert (budget, evidence) == original


def test_insufficient_capacity_does_not_send_or_truncate_the_long_answer():
    budget = {'maxTokens': 100000, 'tokens': 89000, 'reserveTokens': 50000,
              'normalTokens': 42000, 'maxModelCalls': 18, 'modelCalls': 8,
              'reserveModelCalls': 5, 'reservedModelCalls': 5}
    call = Mock()
    result = audit_final_answer('r', 'Whole original question', long_contract(), answers(), [], call, json.loads, budget=budget)
    call.assert_not_called()
    assert result['status'] == 'budget_exhausted' and len(result['gaps']) == 7


def test_length_finish_never_promotes_a_parseable_response_even_with_larger_allowance():
    call = Mock(return_value={'content': '[]', 'finishReason': 'length'})
    result = audit_final_answer('r', 'Whole question', long_contract(), answers(), [], call, json.loads)
    call.assert_called_once()
    assert result['status'] == 'invalid_response' and len(result['gaps']) == 7
