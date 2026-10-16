"""The planning response has one complete shape and never invents missing criteria."""
from copy import deepcopy
import json

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.coverage import validate_plan
from services.deep_research.completion_criteria import validate_completion_criteria
from services.deep_research.graph import make_plan_node


def valid_plan():
    return [{'itemId': 'p', 'question': 'Which evaluation conditions support the claim?',
             'obligations': [{'obligationId': 'o', 'question': 'Identify the reported conditions',
                              'requiredSources': ['paper'], 'completionCriteria': [
                                  {'criterionId': 'conditions', 'requirement': 'State the reported evaluation conditions',
                                   'responseType': 'identification'}]}]}]


def invoke_node(response, *, new_contract=True):
    record = {'question': 'Check the author-reported claim, conditions and unverified scope.',
              'state': {'outputKind': 'claim_verification'}, 'materials': [{'materialId': 'paper'}]}
    if new_contract:
        record['planCompletionContractVersion'] = 1
    calls = []
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return deepcopy(record)
    def invoke(run, node, prompt, options):
        calls.append({'node': node, 'prompt': prompt, 'options': options})
        return response
    result = make_plan_node(invoke, update, validate_plan)({'run_id': 'r'})
    return result, record, calls


def test_primary_schema_and_complete_example_both_include_every_required_criterion_field():
    result, record, calls = invoke_node({'content': json.dumps(valid_plan())})
    assert result['plan_ids'] == ['p'] and len(calls) == 1
    prompt = calls[0]['prompt']
    fields = prompt.split('- obligations: array of {', 1)[1].split('}', 1)[0]
    assert 'completionCriteria' in fields
    shape = json.loads(prompt.split('on EVERY obligation):\n', 1)[1].split('\nReturn only', 1)[0])
    validate_completion_criteria(validate_plan(shape), required=True)
    criterion = shape[0]['obligations'][0]['completionCriteria'][0]
    assert set(criterion) == {'criterionId', 'requirement', 'responseType'}
    assert '<neutral description' in criterion['requirement']
    assert record['state']['planFormatValidation'] == {'status': 'validated', 'requiresCompletionCriteria': True}


def test_valid_response_preserves_model_defined_requirements_without_extra_call():
    expected = valid_plan()
    result, record, calls = invoke_node({'content': json.dumps(expected), 'finishReason': 'stop'})
    assert result['plan_ids'] == ['p']
    assert record['state']['plan'][0]['obligations'][0]['completionCriteria'] == expected[0]['obligations'][0]['completionCriteria']
    assert [c['node'] for c in calls] == ['plan']


def test_missing_completion_fields_still_reject_without_autofill_or_regeneration():
    value = valid_plan()
    value[0]['obligations'][0].pop('completionCriteria')
    result, record, calls = invoke_node({'content': '```json\n' + json.dumps(value) + '\n```', 'finishReason': 'stop'})
    assert result['error_code'] == 'invalid_plan_response' and not result['plan_ids']
    assert 'plan' not in record['state'] and len(calls) == 1
    assert record['state']['planFormatValidation'] == {
        'status': 'rejected', 'reason': 'Each obligation needs one to four completion criteria'}


@pytest.mark.parametrize('malformed', [[], {}, {'items': []}, 'not JSON'])
def test_invalid_plan_keeps_a_bounded_diagnostic_and_never_starts_a_repair(malformed):
    result, record, calls = invoke_node({'content': json.dumps(malformed)})
    assert result['error_code'] == 'invalid_plan_response'
    assert 'plan' not in record['state'] and len(calls) == 1
    assert record['state']['planFormatValidation']['status'] == 'rejected'
    assert len(record['state']['planFormatValidation']['reason']) <= 500


@pytest.mark.parametrize('as_dataclass', [False, True])
def test_truncated_response_cannot_be_accepted_even_if_its_json_parses(as_dataclass):
    content = json.dumps(valid_plan())
    response = (LLMResult('fixture', 'fixture', content, LLMUsage(1, 1, 2), finish_reason='length')
                if as_dataclass else {'content': content, 'finishReason': 'length'})
    result, record, calls = invoke_node(response)
    assert result['error_code'] == 'invalid_plan_response' and len(calls) == 1
    assert 'plan' not in record['state']
    assert record['state']['planFormatValidation']['reason'] == 'Plan response was truncated'


def test_old_run_without_completion_contract_does_not_gain_new_requirements():
    value = valid_plan()
    value[0]['obligations'][0].pop('completionCriteria')
    result, record, calls = invoke_node({'content': json.dumps(value)}, new_contract=False)
    assert result['plan_ids'] == ['p'] and len(calls) == 1
    assert 'completionCriteria' not in calls[0]['prompt']
    assert 'completionCriteria' not in record['state']['plan'][0]['obligations'][0]
