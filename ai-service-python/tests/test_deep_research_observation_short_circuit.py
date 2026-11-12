from copy import deepcopy
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.partitioned_scope_review import review, short_circuit_enabled
from services.deep_research.review_diagnostics import DiagnosticAudit
from services.deep_research.review_response_failure import ResponseAudit
from test_deep_research_partitioned_scope_review import inputs


def fixture(outcomes, *, enabled=True):
    claim, expression, record, evidence = inputs()
    expression['observedSettings'].append({'subject': 'Method A', 'attribute': 'other setting', 'value': '70%'})
    observed = []
    def check(claims, ev, context, node):
        assert len(claims) == 1 and context == []
        observed.append(claims[0]['claimId'])
        value = outcomes[len(observed)-1]
        if isinstance(value, Exception): raise value
        return [{'claimId': claims[0]['claimId'], **deepcopy(value)}]
    checker = SimpleNamespace(_scope_observation_assertions=False,
        _known_single_review_failure=True, _isolate_factual_claims=True,
        _short_circuit_scope_observations=enabled, _check=check,
        _invoke=Mock(side_effect=AssertionError('No entailment for a failed observation')))
    return checker, claim, expression, evidence, observed


@pytest.mark.parametrize('failure', [
    {'status': 'failed', 'reason': 'Source contradicts the setting.'},
    {'status': 'failed', 'reason': 'Invalid diagnostic, still unverified.',
     'executionState': 'received_invalid',
     'reviewDiagnosticAudit': DiagnosticAudit({'version': 1, 'errors': ['diagnostic_source_not_bound']})},
    {'status': 'failed', 'reason': 'No time admission.', 'executionState': 'not_started',
     'reviewTimeAdmission': {'remaining': 0}},
    {'status': 'failed', 'reason': 'Received invalid reply.', 'executionState': 'received_invalid',
     'reviewResponseAudit': ResponseAudit(version=1, responseState='received_invalid')},
])
def test_first_failure_stops_only_its_parent_and_keeps_unreviewed_items_explicit(failure):
    c, claim, expression, ev, observed = fixture([failure])
    before = deepcopy((claim, expression, ev))
    result = review(c, claim, expression, ev, 'verify')
    assert result['claimId'] == claim['claimId'] and result['status'] == 'failed'
    audit = result['partitionedScopeAudit']
    assert len(observed) == len(audit['observedSettings']) == 1
    assert len(audit['unreviewedObservationIds']) == 1
    assert audit['unreviewedPropositionCount'] == 1
    assert audit['observationSchedulingVersion'] == 1
    if 'reviewDiagnosticAudit' in failure:
        assert isinstance(result['reviewDiagnosticAudit'], DiagnosticAudit)
    c._invoke.assert_not_called()
    assert (claim, expression, ev) == before


def test_prior_pass_is_retained_but_does_not_upgrade_a_failed_parent():
    c, claim, expression, ev, observed = fixture([
        {'status': 'passed', 'reason': 'Supported.'}, {'status': 'failed', 'reason': 'Mismatch.'}])
    result = review(c, claim, expression, ev, 'verify_repair')
    assert result['status'] == 'failed' and len(observed) == 2
    assert result['partitionedScopeAudit']['observedSettings'][0]['status'] == 'passed'
    assert result['partitionedScopeAudit']['unreviewedObservationIds'] == []
    c._invoke.assert_not_called()


def test_legacy_policy_still_checks_all_observations_before_aggregating_failure():
    c, claim, expression, ev, observed = fixture([
        {'status': 'failed', 'reason': 'Mismatch.'}, {'status': 'passed', 'reason': 'Supported.'}], enabled=False)
    result = review(c, claim, expression, ev, 'verify')
    assert result['status'] == 'failed' and len(observed) == 2
    assert 'observationSchedulingVersion' not in result['partitionedScopeAudit']


def test_unknown_error_is_propagated_without_becoming_a_semantic_failure():
    error = DeepResearchError('external_call_unknown', 'Original request is unknown')
    c, claim, expression, ev, observed = fixture([error])
    with pytest.raises(DeepResearchError) as caught: review(c, claim, expression, ev, 'verify')
    assert caught.value is error and len(observed) == 1
    c._invoke.assert_not_called()


def test_policy_requires_exact_frozen_server_version():
    assert short_circuit_enabled({'scopeExpressionReviewContractVersion': 4})
    for value in (None, True, False, 0, 1, 2, 3, '4', 5):
        assert not short_circuit_enabled({'scopeExpressionReviewContractVersion': value})


def test_all_passed_observations_still_require_entailment_and_match_the_old_result():
    from test_deep_research_partitioned_scope_review import checker_for
    claim, expression, record, ev = inputs()
    old, old_calls = checker_for(claim, expression, record, ev)
    new, new_calls = checker_for(claim, expression, record, ev)
    new._short_circuit_scope_observations = True
    assert new([claim], ev) == old([claim], ev)
    assert new_calls == old_calls and len(new_calls) == 2
    assert 'Review evidence ENTAILMENT' in new_calls[-1]['prompt']
