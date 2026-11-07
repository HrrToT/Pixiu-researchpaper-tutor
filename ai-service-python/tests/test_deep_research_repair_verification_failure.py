"""Known malformed repair verification must not erase previously verified work."""
from copy import deepcopy
import json
from unittest.mock import Mock, patch

import pytest

from llm.provider import LLMProviderError
from services.deep_research.contracts import DeepResearchError
from services.deep_research.graph import make_verify_node, make_publish_node
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import make_evidence, verify_claims


def fixture(response=None, failure=None):
    evidence = make_evidence({'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash',
        'accessLevel': 'fulltext'}, 'A supported finding.', 'A supported finding.',
        location={'page': 1}, obligation_ids=[])
    claims = [{'claimId': identity, 'kind': 'reported', 'text': text,
               'evidenceRefs': [evidence['evidenceId']]}
              for identity, text in [('keep', 'A supported finding.'), ('repair', 'An unsupported broad finding.')]]
    record = {'question': 'Explain the two findings.', 'state': {
        'outputKind': 'direction_survey', 'reportBody': {'claims': claims}, 'evidence': [evidence], 'plan': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def revision_invoke(**kwargs):
        if failure:
            raise failure
        return response or {'content': '[{"claimId":"repair","status":"passed"', 'finishReason': 'stop'}
    dispatch = Mock(side_effect=revision_invoke)
    class Checker:
        def __call__(self, claims, evidence):
            return [{'claimId': c['claimId'], 'status': 'passed' if c['claimId'] == 'keep' else 'failed'} for c in claims]
        def check_revisions(self, claims, evidence, context):
            return BudgetedSemanticChecker(dispatch, 'r').check_revisions(claims, evidence, context)
    rewrite = Mock(return_value={'content': json.dumps([{**claims[1], 'text': 'A supported finding.'}])})
    node = make_verify_node(verify_claims, Checker(), update, rewrite)
    return lambda: record, update, node, dispatch, rewrite


def coverage():
    return {'status': 'checked', 'gaps': [{'question': 'The second finding remains unresolved.', 'wholeQuestion': True}]}


@pytest.mark.parametrize('response', [None,
    {'content': '[{"claimId":"wrong-id","status":"passed"}]', 'finishReason': 'stop'},
    {'content': '[{"claimId":"repair","status":"passed"}]', 'finishReason': 'length'}])
def test_known_invalid_response_publishes_only_prior_verified_content(response):
    get, update, node, dispatch, rewrite = fixture(response=response)
    with patch('services.deep_research.final_coverage.audit_final_answer', return_value=coverage()):
        result = node({'run_id': 'r'})
    saved = get()['state']
    assert result['claim_ids'] == ['keep']
    assert saved['repairStatus'] == 'verification_invalid_response'
    assert saved['repairCompleted'] is True
    assert saved['verifiedReport']['verifiedClaims'][0]['text'] == 'A supported finding.'
    assert saved['verifiedReport']['rejectedClaims'][0]['claimId'] == 'repair'
    assert dispatch.call_count == rewrite.call_count == 1
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    outcome = make_publish_node(publish, update)({'run_id': 'r'})
    assert outcome['outcome'] == 'partial'
    assert [c['claimId'] for c in publish.call_args.kwargs['payload']['claims']] == ['keep']
    assert '补充核验未完成' in publish.call_args.kwargs['payload']['limitations']


def test_interruption_after_failure_checkpoint_never_resends_rewrite_or_verifier():
    get, update, node, dispatch, rewrite = fixture()
    with patch('services.deep_research.final_coverage.audit_final_answer', return_value=coverage()):
        node({'run_id': 'r'})
        saved = deepcopy(get())
        saved['state'].pop('verifiedReport')
        saved['state'].pop('repairCompleted')
        update('r', lambda _: saved)
        node({'run_id': 'r'})
    assert dispatch.call_count == rewrite.call_count == 1
    assert [c['claimId'] for c in get()['state']['verifiedReport']['verifiedClaims']] == ['keep']


@pytest.mark.parametrize('failure', [
    LLMProviderError('timeout', provider='fixture', model='fixture'),
    DeepResearchError('scope_revoked', 'Scope was revoked.'),
    RuntimeError('Unexpected verifier failure'),
])
def test_unknown_scope_and_unclassified_failures_are_not_swallowed(failure):
    get, update, node, dispatch, rewrite = fixture(failure=failure)
    with patch('services.deep_research.final_coverage.audit_final_answer', return_value=coverage()):
        with pytest.raises(DeepResearchError):
            node({'run_id': 'r'})
    assert 'repairVerificationError' not in get()['state']
    assert 'verifiedReport' not in get()['state']


def test_initial_verification_failure_cannot_publish_unchecked_draft():
    evidence = make_evidence({'workId': 'p', 'versionId': 'v', 'contentHash': 'h', 'accessLevel': 'fulltext'},
        'A finding.', 'A finding.', location={}, obligation_ids=[])
    record = {'state': {'reportBody': {'claims': [{'claimId': 'c', 'kind': 'reported',
        'text': 'A finding.', 'evidenceRefs': [evidence['evidenceId']]}]}, 'evidence': [evidence]}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    node = make_verify_node(verify_claims, BudgetedSemanticChecker(
        lambda **kwargs: {'content': 'not JSON', 'finishReason': 'stop'}, 'r'), update, Mock())
    with pytest.raises(DeepResearchError, match='声明核验未完整返回'):
        node({'run_id': 'r'})
    assert 'verifiedReport' not in record['state']
