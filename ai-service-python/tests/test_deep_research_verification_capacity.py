import json

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.tools import BudgetedSemanticChecker, TrackedLLMInvoker


def targets_from(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Claims:\n', 1)[1].lstrip())[0]


def test_oversized_multi_target_verification_splits_before_sending_and_preserves_permissions():
    claims = [{'claimId': key, 'kind': 'reported', 'text': 'Finding ' + key,
               'evidenceRefs': ['e' + key]} for key in ('a', 'b')]
    evidence = [{'evidenceId': 'e' + key, 'quote': key * 14000} for key in ('a', 'b')]
    sent = []

    def invoke(**request):
        prompt = request['prompt']
        sent.append(request)
        assert len(prompt.encode()) <= 24000
        targets = targets_from(prompt)
        assert len(targets) == 1
        key = targets[0]['claimId']
        assert key * 14000 in prompt
        assert ('b' if key == 'a' else 'a') * 14000 not in prompt
        return {'content': json.dumps([{'claimId': key, 'status': 'passed'}])}

    verdicts = BudgetedSemanticChecker(invoke, 'r')(claims, evidence)
    assert [v['claimId'] for v in verdicts] == ['a', 'b']
    assert all(v['status'] == 'passed' for v in verdicts)
    assert len(sent) == 2
    assert all(r['use_reserve'] is True and r['node'] == 'verify' for r in sent)


def test_capacity_split_does_not_swallow_budget_exhaustion_or_retry():
    calls = []

    def invoke(**request):
        calls.append(request)
        raise BudgetExhaustedError('modelCalls', 1, 1)

    claims = [{'claimId': key, 'kind': 'reported', 'text': key,
               'evidenceRefs': [key]} for key in ('a', 'b')]
    evidence = [{'evidenceId': key, 'quote': key * 14000} for key in ('a', 'b')]
    with pytest.raises(BudgetExhaustedError):
        BudgetedSemanticChecker(invoke, 'r')(claims, evidence)
    assert len(calls) == 1


def test_single_unfit_target_is_not_retried_and_cannot_pass_without_its_evidence():
    calls = []

    def invoke(**request):
        calls.append(request)
        return {'content': '[{"claimId":"a","status":"passed"}]'}

    verdicts = BudgetedSemanticChecker(invoke, 'r')(
        [{'claimId': 'a', 'kind': 'reported', 'text': 'Finding', 'evidenceRefs': ['a']}],
        [{'evidenceId': 'a', 'quote': 'a' * 30000}])
    assert verdicts[0]['status'] == 'failed'
    assert len(calls) == 0


def test_single_fixed_content_overflow_is_a_budget_failure_before_provider_send():
    def invoke(**request):
        pytest.fail('A request known to exceed capacity must not be sent')

    with pytest.raises(BudgetExhaustedError) as error:
        BudgetedSemanticChecker(invoke, 'r')(
            [{'claimId': 'a', 'kind': 'reported', 'text': 'a' * 30000, 'evidenceRefs': []}], [])
    assert error.value.details['kind'] == 'verificationPromptBytes'


def test_source_registry_preserves_versions_and_quotes_without_repeating_metadata():
    captured = []
    evidence = [{'evidenceId': key, 'quote': 'Quote ' + key, 'sourceWorkId': 'same-paper',
                 'sourceVersionId': version, 'sourceTitle': 'A shared paper title'}
                for key, version in [('a', 'v1'), ('b', 'v1'), ('c', 'v2')]]
    claims = [{'claimId': 'claim', 'kind': 'reported', 'text': 'Finding',
               'evidenceRefs': ['a', 'b', 'c']}]

    def invoke(**request):
        captured.append(request['prompt'])
        return {'content': '[{"claimId":"claim","status":"failed"}]'}

    BudgetedSemanticChecker(invoke, 'r')(claims, evidence)
    view = json.JSONDecoder().raw_decode(captured[0].split('Evidence:\n', 1)[1].lstrip())[0]
    assert len(view['sources']) == 2
    assert {s['versionId'] for s in view['sources'].values()} == {'v1', 'v2'}
    assert all(s['workId'] == 'same-paper' for s in view['sources'].values())
    assert [e['quote'] for e in view['evidence'].values()] == ['Quote a', 'Quote b', 'Quote c']
    assert view['evidence']['E1']['source'] == view['evidence']['E2']['source']
    assert view['evidence']['E3']['source'] != view['evidence']['E1']['source']


def test_split_design_targets_keep_complete_sibling_definitions_as_context():
    claims = [{'claimId': key, 'kind': 'proposal', 'designRole': 'limits',
               'text': 'Prospective limitation ' + key, 'designContractVersion': 2,
               'executionSpec': {'sharedRule': key + '-must-be-retained'},
               'evidenceRefs': ['e' + key]} for key in ('a', 'b')]
    evidence = [{'evidenceId': 'e' + key, 'quote': key * 10000} for key in ('a', 'b')]
    sent = []

    def invoke(**request):
        sent.append(request['prompt'])
        assert 'a-must-be-retained' in request['prompt']
        assert 'b-must-be-retained' in request['prompt']
        targets = targets_from(request['prompt'])
        assert len(targets) == 1
        # Context is retained for consistency; it is never a verdict target.
        return {'content': json.dumps([{'claimId': targets[0]['claimId'], 'status': 'failed'}])}

    BudgetedSemanticChecker(invoke, 'r').check_revisions(claims, evidence, [])
    assert len(sent) == 2


def test_small_batch_stays_one_request_and_fixed_content_overflow_splits_before_dispatch():
    for text_size, expected_calls in [(10, 1), (14000, 2)]:
        claims = [{'claimId': key, 'kind': 'reported', 'text': key * text_size,
                   'evidenceRefs': []} for key in ('a', 'b')]
        sent = []

        def invoke(**request):
            sent.append(request['prompt'])
            assert len(request['prompt'].encode()) <= 24000
            return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'failed'}
                                           for c in targets_from(request['prompt'])])}

        BudgetedSemanticChecker(invoke, 'r')(claims, [])
        assert len(sent) == expected_calls


def test_split_replay_reuses_settled_first_request_after_interruption():
    from llm.provider import LLMResult, LLMUsage

    ledger, sent = {}, []
    interrupted = False

    def reserve(**request):
        nonlocal interrupted
        identity = request['args_digest']
        if identity in ledger:
            assert 'result' in ledger[identity]
            return ledger[identity], True
        if ledger and not interrupted:
            interrupted = True
            raise DeepResearchError('fixture_interruption', 'Interrupted before second dispatch')
        row = {'callId': identity, 'reservationToken': identity}
        ledger[identity] = row
        return row, False

    def complete(identity, **settlement):
        assert settlement['status'] == 'succeeded'
        ledger[identity]['result'] = settlement['result']

    class Provider:
        def invoke(self, request):
            targets = targets_from(request.prompt)
            sent.append(targets[0]['claimId'])
            return LLMResult(content=json.dumps([{'claimId': c['claimId'], 'status': 'failed'}
                                                for c in targets]),
                             provider='fixture', model='fixture', usage=LLMUsage(8, 2, 10))

    checker = BudgetedSemanticChecker(TrackedLLMInvoker(Provider(), reserve, complete), 'r')
    claims = [{'claimId': key, 'kind': 'reported', 'text': key, 'evidenceRefs': [key]}
              for key in ('a', 'b')]
    evidence = [{'evidenceId': key, 'quote': key * 14000} for key in ('a', 'b')]
    with pytest.raises(DeepResearchError, match='Interrupted before second dispatch'):
        checker(claims, evidence)
    assert sent == ['a']
    verdicts = checker(claims, evidence)
    assert sent == ['a', 'b']
    assert [v['claimId'] for v in verdicts] == ['a', 'b']
    assert len(ledger) == 2
