from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from services.deep_research.coverage_repair import prepare_coverage_repair
from services.deep_research.review_diagnostics import DiagnosticAudit


def inputs():
    claim = {'claimId': 'pending', 'kind': 'reported', 'text': 'An unresolved answer.',
             'obligationIds': ['o1'], 'evidenceRefs': []}
    rejection = {'claimId': 'pending', 'reason': 'semantic_unresolved',
                 'executionState': 'received_invalid',
                 'reviewDiagnosticAudit': DiagnosticAudit({
                     'version': 1, 'reportedStatus': 'passed',
                     'errors': ['diagnostic_source_not_bound']})}
    audit = {'status': 'checked', 'gaps': [
        {'obligationId': 'o1', 'question': 'Explain point 1'},
        {'obligationId': 'answer_scope', 'question': 'Explain all', 'wholeQuestion': True}]}
    return {'claims': [claim]}, {'accepted': [], 'rejected': [rejection]}, audit


def test_invalid_diagnostic_is_only_deferred_under_new_policy():
    report, verification, audit = inputs()
    original = deepcopy((report, verification, audit))
    # The previous malformed-response policy must keep its exact behavior.
    assert prepare_coverage_repair(report, verification, audit, defer_invalid_reviews=True)['rejected']
    result = prepare_coverage_repair(report, verification, audit, defer_invalid_diagnostics=True)
    assert result == {'accepted': [], 'rejected': [], 'deferredReviewClaims': ['pending']}
    assert (report, verification, audit) == original


def test_model_json_cannot_forge_diagnostic_deferral():
    report, verification, audit = inputs()
    verification['rejected'][0]['reviewDiagnosticAudit'] = dict(verification['rejected'][0]['reviewDiagnosticAudit'])
    assert prepare_coverage_repair(report, verification, audit, defer_invalid_diagnostics=True)['rejected']


def test_valid_diagnostic_and_other_genuine_failure_still_need_repair():
    report, verification, audit = inputs()
    other = {'claimId': 'bad', 'obligationIds': ['o2'], 'text': 'A genuine mismatch.'}
    report['claims'].append(other)
    verification['rejected'].append({'claimId': 'bad', 'reason': 'semantic_unresolved'})
    audit['gaps'].append({'obligationId': 'o2', 'question': 'Fix the actual mismatch'})
    result = prepare_coverage_repair(report, verification, audit, defer_invalid_diagnostics=True)
    assert [r['claimId'] for r in result['rejected']] == ['bad']
    assert result['deferredReviewClaims'] == ['pending']
    verification['rejected'][0]['reviewDiagnosticAudit']['errors'] = []
    assert len(prepare_coverage_repair(report, verification, audit, defer_invalid_diagnostics=True)['rejected']) == 2


@pytest.mark.parametrize('value', [1, None, 'true'])
def test_policy_is_typed(value):
    with pytest.raises(ValueError):
        prepare_coverage_repair(*inputs(), defer_invalid_diagnostics=value)


def test_graph_keeps_unverified_answer_without_body_repair():
    from services.deep_research.graph import make_verify_node
    report, verification, audit = inputs()
    record = {'question': 'Explain', 'diagnosticRepairRoutingContractVersion': 1,
              'state': {'reportBody': report, 'evidence': [], 'plan': []}}
    def update(rid, fn, **kw):
        nonlocal record
        record = fn(record)
        return record
    invoke = Mock(side_effect=AssertionError('Invalid audit must not edit the body'))
    with patch('services.deep_research.final_coverage.audit_final_answer', return_value=audit):
        result = make_verify_node(lambda *_: deepcopy(verification), None, update, invoke)({'run_id': 'r'})
    invoke.assert_not_called()
    assert result['claim_ids'] == []
    assert record['state']['deferredReviewClaims'] == ['pending']
    assert record['state']['verifiedReport']['verifiedClaims'] == []
    assert record['state']['verifiedReport']['rejectedClaims'][0]['claimId'] == 'pending'


def test_profile_is_frozen_and_old_runs_are_not_upgraded(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    key = 'diagnosticRepairRoutingContractVersion'
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op',
            'question': 'Explain', 'deferStart': True, key: False}, start_async=False)
        assert type(r[key]) is int and r[key] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda r: {**r, key: False})
        old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop(key)
        repo.create_run(old)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run('old', lambda r: {**r, key: 1})
        assert key not in repo.require_run('old')
    finally:
        facade.shutdown()
