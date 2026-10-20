import json
from copy import deepcopy

import pytest

from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.prospective_review import POLICY, enabled
from test_deep_research_shared_experiment_repair import inputs


def requests_for(claims, context=(), *, version=1):
    calls = []
    def invoke(**request):
        calls.append(request)
        targets = json.JSONDecoder().raw_decode(request['prompt'].split('Claims:', 1)[1].lstrip())[0]
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'failed',
            'reason': 'Offline unverified protocol.'} for c in targets])}
    checker = BudgetedSemanticChecker(invoke, 'offline', prospective_review=version,
        research_question='Compare the whole stage quality/storage/extra training tradeoff, descriptive only.',
        experiment_intent_review=3)
    result = checker.check_revisions(claims, inputs()[2], context)
    return calls, result


def test_each_review_partition_receives_calibration_without_discarding_the_actual_protocol():
    report, _, _ = inputs(); before = deepcopy(report)
    calls, result = requests_for(report['claims'])
    assert {c['node'] for c in calls} == {'verify_repair_design_config', 'verify_repair_design_science'}
    assert all(POLICY in c['prompt'] and c['use_reserve'] for c in calls)
    assert all(len(c['prompt'].encode()) <= 24000 for c in calls)
    for request in calls:
        assert 'No quotation proving' in request['prompt'] or 'needs NO quotation' in request['prompt']
        assert 'budgetContractVersion' in request['prompt']
        assert 'Exact' in request['prompt'] or 'exact' in request['prompt']
    assert report == before and all(r['status'] == 'failed' for r in result)


@pytest.mark.parametrize('version', [False, None, True, 0, '1', 2])
def test_nonmatching_and_legacy_versions_keep_the_exact_old_prompt(version):
    report, _, _ = inputs()
    baseline, _ = requests_for(report['claims'], version=False)
    actual, _ = requests_for(report['claims'], version=version)
    assert [c['prompt'] for c in actual] == [c['prompt'] for c in baseline]
    assert not enabled(version)


def test_factual_assertions_do_not_receive_prospective_choice_exemptions():
    calls, result = requests_for([{'claimId': 'fact', 'kind': 'reported', 'text': 'Unsubstantiated measured success.', 'evidenceRefs': []}])
    assert len(calls) == 1 and POLICY not in calls[0]['prompt']
    assert result[0]['status'] == 'failed'


def test_new_policy_does_not_turn_failed_scientific_verdict_into_a_pass():
    report, _, _ = inputs(); claim = next(c for c in report['claims'] if c['designRole'] == 'steps')
    calls = []
    def invoke(**request):
        calls.append(request)
        return {'content': json.dumps([{'claimId': claim['claimId'], 'status': 'failed',
            'reason': 'Missing actual state initialization and incompatible renderer.'}])}
    result = BudgetedSemanticChecker(invoke, 'offline', prospective_review=lambda: 1,
        experiment_intent_review=3).check_revisions([claim], inputs()[2], report['claims'][:-1])
    assert result[0]['status'] == 'failed' and 'Missing actual state' in result[0]['reason']
    assert POLICY in calls[0]['prompt']


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_review_contract_is_server_owned_and_immutable(tmp_path, replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        value, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Design experiment',
            'experimentReviewContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert value['experimentReviewContractVersion'] == 1 and enabled(value['experimentReviewContractVersion'])
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(value['runId'], lambda r: {**r, 'experimentReviewContractVersion': replacement})
    finally:
        facade.shutdown()
