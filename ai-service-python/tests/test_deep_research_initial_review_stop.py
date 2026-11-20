from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError
from services.deep_research.graph import make_verify_node, make_publish_node
from services.deep_research.initial_review_stop import InitialReviewBudgetStop
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims


def material():
    claims = [{'claimId': f'c{i}', 'kind': 'reported', 'text': f'The method retains property {chr(65+i)}.',
               'evidenceRefs': [f'e{i}'], 'conditions': {}} for i in range(3)]
    evidence = [{'evidenceId': f'e{i}', 'quote': c['text'], 'sourceWorkId': f'p{i}',
                 'sourceVersionId': 'v1', 'verification': {'literal': 'passed'}}
                for i, c in enumerate(claims)]
    return claims, evidence


def interrupted_checker(before_stop, error=None, enabled=True):
    requests = []
    def invoke(**kw):
        if len(requests) == before_stop:
            raise error or BudgetExhaustedError('tokens', 100000, 100334)
        requests.append(kw)
        target = json.JSONDecoder().raw_decode(kw['prompt'].split('Claims:\n', 1)[1])[0][0]
        return {'content': json.dumps([{'claimId': target['claimId'], 'status': 'passed'}])}
    return BudgetedSemanticChecker(invoke, 'r', isolate_factual_claims=True,
        preserve_initial_review_budget=enabled), requests


@pytest.mark.parametrize('before_stop', [0, 1, 2])
def test_checker_preserves_only_completed_batches_and_does_not_continue(before_stop):
    checker, requests = interrupted_checker(before_stop)
    claims, evidence = material()
    with pytest.raises(InitialReviewBudgetStop) as caught:
        checker(claims, evidence)
    assert [r['claimId'] for r in caught.value.verdicts] == [f'c{i}' for i in range(before_stop)]
    assert len(requests) == before_stop
    assert caught.value.details == {'kind': 'tokens', 'limit': 100000, 'used': 100334}


@pytest.mark.parametrize('mode', ['legacy', 'revision', 'unknown'])
def test_other_policies_and_unknown_calls_still_propagate(mode):
    error = UnknownCallError('unknown') if mode == 'unknown' else BudgetExhaustedError('tokens', 1, 2)
    checker, requests = interrupted_checker(1, error, enabled=mode != 'legacy')
    claims, evidence = material()
    with pytest.raises(type(error)) as caught:
        if mode == 'revision':
            checker.check_revisions(claims, evidence, [])
        else:
            checker(claims, evidence)
    assert not isinstance(caught.value, InitialReviewBudgetStop)
    assert len(requests) == 1


@pytest.mark.parametrize('before_stop', [0, 2])
def test_production_verify_retains_results_and_reopens_without_requests(before_stop, tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    claims, evidence = material()
    record = {'runId': 'r', 'status': 'running', 'question': 'Compare the methods.',
              'comparisonAuthoringContractVersion': 2, 'comparisonPlanningContractVersion': 6,
              'comparisonReviewBatchContractVersion': 2,
              'state': {'outputKind': 'paper_comparison', 'reportBody': {'claims': claims},
                        'evidence': evidence, 'plan': []}}
    db_path = tmp_path / 'review.sqlite3'
    repo = DeepResearchRepository(db_path)
    repo.initialize()
    repo.create_run(record)
    checker, requests = interrupted_checker(before_stop)
    invoke = Mock(side_effect=AssertionError('No audit or repair after initial review stop'))
    node = make_verify_node(verify_claims, checker, repo.update_run, llm_invoke=invoke)
    node({'run_id': 'r'})
    record = repo.require_run('r')
    saved = deepcopy(record['state'])
    result = saved['verifiedReport']
    assert len(result['verifiedClaims']) == before_stop
    assert len(result['rejectedClaims']) == 3-before_stop
    assert all(c['executionState'] == 'not_started' for c in result['rejectedClaims'])
    assert result['answerCoverage']['status'] == 'not_checked'
    assert saved['initialVerification']['accepted'] == result['verifiedClaims']
    reopened = DeepResearchRepository(db_path)
    reopened.initialize()
    never_review = Mock(side_effect=AssertionError('Stopped review must not resend'))
    node = make_verify_node(verify_claims, never_review, reopened.update_run, llm_invoke=invoke)
    node({'run_id': 'r'})
    assert reopened.require_run('r')['state'] == saved
    assert len(requests) == before_stop
    invoke.assert_not_called()
    record['state']['evidence'][0]['quote'] += ' Changed.'
    reopened.update_run('r', lambda r: {**r, 'state': record['state']})
    with pytest.raises(ValueError, match='inputs changed'):
        node({'run_id': 'r'})
    never_review.assert_not_called()
    reopened.update_run('r', lambda r: {**r, 'state': saved})
    publish = make_publish_node(reopened.publish_report, reopened.update_run)
    published = publish({'run_id': 'r', 'execution_epoch': 0})
    assert published['outcome'] == ('partial' if before_stop else 'inconclusive')
    result = reopened.require_run('r')['result']
    assert {c['claimId'] for c in result['claims']} == {f'c{i}' for i in range(before_stop)}
    assert '完整比较尚未完成' in result['limitations']


def test_decomposed_expression_budget_stop_does_not_promote_partial_parent():
    from test_deep_research_partitioned_scope_review import inputs
    ordinary, ordinary_evidence = material()
    parent, expression, _, expression_evidence = inputs()
    checker = BudgetedSemanticChecker(Mock(), 'r', partitioned_scope_review=True,
        scope_expression_context=lambda _: {parent['claimId']: expression},
        preserve_initial_review_budget=True)
    checker._check_batch = Mock(return_value=[{'claimId': c['claimId'], 'status': 'passed'} for c in ordinary])
    from unittest.mock import patch
    with patch('services.deep_research.partitioned_scope_review.review',
               side_effect=InitialReviewBudgetStop(BudgetExhaustedError('tokens', 1, 2),
                   [{'claimId': 'synthetic_child', 'status': 'passed'}])):
        with pytest.raises(InitialReviewBudgetStop) as caught:
            checker([*ordinary, parent], [*ordinary_evidence, *expression_evidence])
    assert [v['claimId'] for v in caught.value.verdicts] == [c['claimId'] for c in ordinary]
