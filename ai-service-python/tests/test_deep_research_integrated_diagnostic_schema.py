from copy import deepcopy
import json

import pytest

from services.deep_research.factual_decision import prompt
from test_deep_research_factual_decision import checker, response, target, evidence


def test_required_field_is_in_primary_row_schema_without_changing_claims_or_evidence():
    old = prompt('exact claims', 'exact evidence')
    new = prompt('exact claims', 'exact evidence', diagnostic_facts=True)
    assert 'with claimId, a concise reason, scopeAudit, and diagnosticFacts.' in new
    assert 'mandatory for BOTH supported=true and supported=false' in new
    assert 'including [] when the reason' in new
    assert old.split('Return a JSON array')[0] == new.split('Return a JSON array')[0]
    assert old[old.index('scopeAudit.supported is'): ] == new[new.index('scopeAudit.supported is'): ]
    assert prompt('exact claims', 'exact evidence', diagnostic_facts=False) == old


@pytest.mark.parametrize('value', [1, None, 'true'])
def test_schema_policy_is_typed(value):
    with pytest.raises(ValueError):
        prompt('claims', 'evidence', diagnostic_facts=value)


@pytest.mark.parametrize('supported', [True, False])
def test_explicit_empty_diagnostics_preserve_the_actual_decision(supported):
    sent = []
    raw = {**response(supported), 'diagnosticFacts': []}
    def invoke(**kw):
        sent.append(kw)
        return {'content': json.dumps([raw])}
    result = checker(invoke, review_diagnostic_bindings=True,
                     integrated_diagnostic_schema=True)([target()], evidence())[0]
    assert len(sent) == 1
    assert 'scopeAudit, and diagnosticFacts.' in sent[0]['prompt']
    assert result['status'] == ('passed' if supported else 'failed')
    assert result['reviewDiagnosticAudit']['errors'] == []


def test_missing_array_is_not_inserted_or_approved():
    raw = response(True); before = deepcopy(raw); calls = []
    def invoke(**kw):
        calls.append(kw)
        return {'content': json.dumps([raw])}
    result = checker(invoke, review_diagnostic_bindings=True,
                     integrated_diagnostic_schema=True)([target()], evidence())[0]
    assert result['status'] == 'failed' and result['executionState'] == 'received_invalid'
    assert result['reviewDiagnosticAudit']['errors'] == ['diagnostic_facts_missing_or_invalid']
    assert len(calls) == 1 and raw == before


def test_old_checker_prompt_and_decision_are_exact_when_new_schema_is_off():
    raw = {**response(), 'diagnosticFacts': []}; sent = []
    def invoke(**kw):
        sent.append(deepcopy(kw))
        return {'content': json.dumps([raw])}
    first = checker(invoke, review_diagnostic_bindings=True)([target()], evidence())
    old_request = sent.pop()
    for value in (False, None, 0, 1, '1'):
        assert checker(invoke, review_diagnostic_bindings=True,
            integrated_diagnostic_schema=value)([target()], evidence()) == first
        assert sent.pop() == old_request


def test_new_schema_requires_active_diagnostic_gate():
    sent = []
    def invoke(**kw):
        sent.append(kw)
        return {'content': json.dumps([response()])}
    checker(invoke, integrated_diagnostic_schema=True)([target()], evidence())
    assert 'scopeAudit, and diagnosticFacts.' not in sent[0]['prompt']
