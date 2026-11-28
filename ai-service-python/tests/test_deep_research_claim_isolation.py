import json

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import BudgetedSemanticChecker


def facts():
    claims = [{'claimId': key, 'kind': 'reported' if key == 'a' else 'inference',
               'text': 'Finding '+key, 'evidenceRefs': ['e'+key]} for key in ('a', 'b', 'c')]
    evidence = [{'evidenceId': 'e'+key, 'quote': 'OWN ORIGINAL '+key,
                 'sourceWorkId': 'paper'+key, 'sourceVersionId': 'v1'} for key in ('a', 'b', 'c')]
    return claims, evidence


@pytest.mark.parametrize('revision', [False, True])
def test_each_fact_receives_only_its_own_cited_originals_even_when_batch_fits(revision):
    claims, evidence = facts(); requests = []
    def invoke(**request):
        prompt = request['prompt']; requests.append(request)
        targets = json.JSONDecoder().raw_decode(prompt.split('Claims:\n', 1)[1])[0]
        sources = json.JSONDecoder().raw_decode(prompt.split('Evidence:\n', 1)[1])[0]
        assert len(targets) == len(sources['evidence']) == len(sources['sources']) == 1
        key = targets[0]['claimId']
        assert 'OWN ORIGINAL '+key in prompt
        assert all('OWN ORIGINAL '+other not in prompt for other in ('a', 'b', 'c') if other != key)
        return {'content': json.dumps([{'claimId': key, 'status': 'passed'}])}
    checker = BudgetedSemanticChecker(invoke, 'r', isolate_factual_claims=True)
    output = checker.check_revisions(claims, evidence, []) if revision else checker(claims, evidence)
    assert [v['claimId'] for v in output] == ['a', 'b', 'c']
    assert len(requests) == 3 and all(r['use_reserve'] is True for r in requests)
    assert {r['node'] for r in requests} == {'verify_repair' if revision else 'verify'}


def test_unmarked_legacy_small_answer_retains_its_original_batch():
    claims, evidence = facts(); requests = []
    def invoke(**request):
        requests.append(request)
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'passed'} for c in claims])}
    assert len(BudgetedSemanticChecker(invoke, 'r')(claims, evidence)) == 3
    assert len(requests) == 1


@pytest.mark.parametrize('error', [BudgetExhaustedError('modelCalls', 2, 2), DeepResearchError('unresolved_unknown', 'Unknown call')])
def test_isolation_does_not_retry_failed_send_or_continue_later_facts(error):
    claims, evidence = facts(); requests = []
    def invoke(**request):
        requests.append(request)
        if len(requests) == 2:
            raise error
        return {'content': '[{"claimId":"a","status":"passed"}]'}
    with pytest.raises(type(error)) as caught:
        BudgetedSemanticChecker(invoke, 'r', isolate_factual_claims=True)(claims, evidence)
    assert caught.value is error
    assert len(requests) == 2


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_claim_isolation_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '核查主张',
            'deferStart': True, 'claimIsolationContractVersion': replacement}, start_async=False)
        assert run['claimIsolationContractVersion'] == 1
        assert facade._make_semantic_checker(run['runId'])._isolate_factual_claims() is True
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'claimIsolationContractVersion': replacement})
    finally:
        facade.shutdown()
