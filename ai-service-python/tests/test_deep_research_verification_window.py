import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage, LLMProviderError
from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError, UnresolvedUnknownError
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import BudgetedSemanticChecker, TrackedLLMInvoker
from services.deep_research.verification_capacity import verification_input_limit


def store(tmp_path, *, version=1, budget=None):
    repo = DeepResearchRepository(str(tmp_path / 'window.sqlite3'))
    repo.initialize()
    payload = {'runId': 'r', 'taskId': 't', 'question': 'Check this source.'}
    if version is not None:
        payload['verificationInputContractVersion'] = version
    if budget is not None:
        payload['budget'] = budget
    repo.create_run(payload)
    repo.begin_execution('r')
    return repo


def tracked(repo, provider):
    return TrackedLLMInvoker(provider, repo.reserve_call, repo.complete_call,
        run_record_fn=repo.require_run, verification_max_input_bytes=32000)


@pytest.mark.parametrize('version', [None, True, False, 0, 2, '1'])
def test_legacy_and_invalid_versions_keep_the_old_window(version):
    record = {} if version is None else {'verificationInputContractVersion': version}
    assert verification_input_limit(record, 'verify_design_science', 24000, 32000) == 24000


@pytest.mark.parametrize('node', ['synthesize', 'extract', 'repair_claims', 'verify_answer_coverage',
                                'verify_design_science_extra', ['verify']])
def test_other_nodes_cannot_use_the_verification_window(node):
    assert verification_input_limit({'verificationInputContractVersion': 1}, node, 24000, 32000) == 24000


def test_new_window_reserves_full_bytes_and_settles_measured_usage(tmp_path):
    repo = store(tmp_path)
    provider = Mock()
    provider.invoke.return_value = LLMResult('fixture', 'fixture', '[]', LLMUsage(5500, 500, 6000))
    tracked(repo, provider)('r', 'verify_design_science', 'x' * 27000, {'max_tokens': 4000}, True)
    call, = repo.list_calls('r')
    assert call['reservedTokens'] == 27000 + 1024 + 4000
    assert call['usesReserve'] is True and call['settled'] is True
    assert repo.require_run('r')['budget']['tokens'] == 6000
    assert repo.require_run('r')['budget']['normalTokens'] == 0
    provider.invoke.assert_called_once()


def test_window_does_not_grant_total_budget_or_dispatch_a_refused_call(tmp_path):
    repo = store(tmp_path, budget={'maxTokens': 30000, 'reserveTokens': 30000})
    before = deepcopy(repo.require_run('r')['budget'])
    provider = Mock()
    with pytest.raises(BudgetExhaustedError):
        tracked(repo, provider)('r', 'verify_design_science', 'x' * 27000, {'max_tokens': 4000}, True)
    assert repo.require_run('r')['budget'] == before and repo.list_calls('r') == []
    provider.invoke.assert_not_called()


def test_settled_large_request_is_reused_even_after_remaining_budget_shrinks(tmp_path):
    repo = store(tmp_path)
    provider = Mock()
    provider.invoke.return_value = LLMResult('fixture', 'fixture', '[]', LLMUsage(5000, 1000, 6000))
    options = {'max_tokens': 4000}
    original = tracked(repo, provider)('r', 'verify_design_science', 'x' * 27000, options, True)
    repo.update_run('r', lambda r: {**r, 'budget': {**r['budget'], 'tokens': 99000,
        'normalTokens': 49000, 'reservedModelCalls': 5, 'modelCalls': 12}})
    reopened = DeepResearchRepository(repo.db_path)
    reopened.initialize()
    assert tracked(reopened, provider)('r', 'verify_design_science', 'x' * 27000, options, True) == original
    assert len(repo.list_calls('r')) == 1
    assert repo.require_run('r')['budget']['tokens'] == 99000
    provider.invoke.assert_called_once()


def test_unknown_large_call_stays_unknown_and_blocks_identical_or_new_requests(tmp_path):
    repo = store(tmp_path)
    provider = Mock()
    provider.invoke.side_effect = LLMProviderError('Timeout', provider='fixture', model='fixture', retryable=True)
    invoke = tracked(repo, provider)
    with pytest.raises(LLMProviderError):
        invoke('r', 'verify_design_science', 'x' * 27000, {'max_tokens': 4000}, True)
    before = deepcopy(repo.require_run('r')['budget'])
    with pytest.raises(UnknownCallError):
        invoke('r', 'verify_design_science', 'x' * 27000, {'max_tokens': 4000}, True)
    with pytest.raises(UnresolvedUnknownError):
        invoke('r', 'verify_design_science', 'y' * 27000, {'max_tokens': 4000}, True)
    assert repo.require_run('r')['budget'] == before
    assert len(repo.list_calls('r')) == 1 and repo.list_calls('r')[0]['status'] == 'unknown'
    provider.invoke.assert_called_once()


@pytest.mark.parametrize('version', [None, 1])
def test_new_window_retains_complete_quote_and_context_without_waiving_semantics(tmp_path, version):
    repo = store(tmp_path, version=version)
    quote, surrounding = 'Exact original. ' * 1450, 'Original neighboring condition ' * 15 + '.'
    evidence = [{'evidenceId': 'e', 'quote': quote,
                 'sourceContext': surrounding + quote + surrounding}]
    claims = [{'claimId': 'c', 'kind': 'reported', 'text': 'Check the complete quotation.', 'evidenceRefs': ['e']}]
    provider = Mock()
    provider.invoke.return_value = LLMResult('fixture', 'fixture',
        json.dumps([{'claimId': 'c', 'status': 'failed', 'reason': 'No content approval in an offline fixture.'}]),
        LLMUsage(100, 20, 120))
    result = BudgetedSemanticChecker(tracked(repo, provider), 'r')(claims, evidence)
    assert result[0]['status'] == 'failed'
    if version == 1:
        prompt = provider.invoke.call_args.args[0].prompt
        assert 24000 < len(prompt.encode()) <= 32000
        assert quote in prompt and surrounding in prompt
        provider.invoke.assert_called_once()
    else:
        provider.invoke.assert_not_called()


@pytest.mark.parametrize('new_version', [None, 2, True])
def test_window_contract_cannot_change_during_a_run(tmp_path, new_version):
    repo = store(tmp_path)
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run('r', lambda r: {**r, 'verificationInputContractVersion': new_version})
    assert repo.require_run('r')['verificationInputContractVersion'] == 1


@pytest.mark.parametrize('limit', [True, 0, -1, 32001, '32000'])
def test_invalid_server_window_is_rejected(limit):
    with pytest.raises(ValueError):
        TrackedLLMInvoker(Mock(), Mock(), Mock(), verification_max_input_bytes=limit)


def test_client_cannot_disable_or_expand_the_server_owned_window_contract(tmp_path):
    from services.deep_research.facade import ResearchFacade
    repo = store(tmp_path)
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object())
    try:
        response, created = facade.create({'workspaceTaskId': 't', 'operationKey': 'new',
            'question': 'Explain', 'materials': [], 'verificationInputContractVersion': 999,
            'verificationMaxInputBytes': 1000000}, start_async=False)
        record = repo.require_run(response['runId'])
        assert created and record['verificationInputContractVersion'] == 1
        assert 'verificationMaxInputBytes' not in record
        assert facade._make_llm_invoker(response['runId']).prompt_byte_limit(response['runId'], 'verify') == 32000
        assert facade._make_semantic_checker(response['runId'])._invoke.prompt_byte_limit(response['runId'], 'verify') == 32000
    finally:
        facade.shutdown()


@pytest.mark.parametrize('version', [None, 1])
@pytest.mark.parametrize('changed_prose', [False, True])
def test_context_only_compacts_exact_generated_suffix_under_the_new_contract(tmp_path, version, changed_prose):
    from services.deep_research.execution_materialization import materialize_execution_claim
    repo = store(tmp_path, version=version)
    budget = {'claimId': 'budget', 'kind': 'proposal', 'designRole': 'budget', 'text': 'Original rationale.',
        'designContractVersion': 2, 'budgetContractVersion': 1,
        'executionSpec': {'baseline': {'mode': 'train', 'unit': 'optimizer_steps',
            'maxBudget': 1000, 'stoppingRule': 'At the fixed cap.'},
            'recovery': {'mode': 'matched', 'unit': 'optimizer_steps', 'groups': {'0': 500, '1': 500}}}}
    materialized = materialize_execution_claim(budget)
    if changed_prose:
        materialized['text'] += '\nContradictory original clause must stay visible.'
    target = {'claimId': 'limits', 'kind': 'proposal', 'designRole': 'limits',
              'text': 'Bounded inference only.', 'evidenceRefs': []}
    provider = Mock()
    provider.invoke.return_value = LLMResult('fixture', 'fixture',
        '[{"claimId":"limits","status":"failed"}]', LLMUsage(100, 10, 110))
    before = deepcopy(materialized)
    BudgetedSemanticChecker(tracked(repo, provider), 'r').check_revisions([target], [], [materialized])
    prompt = provider.invoke.call_args.args[0].prompt
    context = json.JSONDecoder().raw_decode(prompt.split(
        'Other proposed statements, for consistency only (not evidence and not verdict targets):\n', 1)[1])[0]
    expected = budget['text'] if version == 1 and not changed_prose else materialized['text']
    assert context[0]['text'] == expected and context[0]['executionSpec'] == budget['executionSpec']
    assert materialized == before


def test_new_hard_window_overflow_stops_before_reservation(tmp_path):
    repo = store(tmp_path)
    provider = Mock()
    with pytest.raises(ValueError, match='Prompt too large'):
        tracked(repo, provider)('r', 'verify_design_science', 'x' * 32001, {'max_tokens': 4000}, True)
    assert repo.list_calls('r') == []
    provider.invoke.assert_not_called()
