from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research import adaptive_assessment as assessment
from services.deep_research.contracts import DeepResearchError
from test_deep_research_evidence_requirements import store, evidence, run, rows, verdicts


def caps_for(repo, take):
    record = repo.require_run('r')
    obligations = {o['obligationId']: o for item in record['state']['plan'] for o in item['obligations']}
    pairs = assessment._pairs(record, obligations)
    selected = [{**row, 'pairId': f'R{i+1}'} for i, row in enumerate(pairs[:take])]
    return len(assessment._prompt(selected).encode('utf8')) + 1


def test_new_literal_input_precedes_old_unchecked_backlog_without_bigger_window(tmp_path, monkeypatch):
    repo, output = store(tmp_path, evidenceCoverageContractVersion=3)
    backlog = evidence('An older rendering detail does not establish the previous-state relationship.', 2)
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [output, backlog]}})
    cap = caps_for(repo, 2)
    monkeypatch.setattr(assessment, '_input_limit', lambda _: cap)
    def first(rid, node, prompt, options):
        assert len(prompt.encode('utf8')) <= cap
        assert {row['evidenceId'] for row in rows(prompt)} == {output['evidenceId']}
        return verdicts(prompt)
    result = run(repo, first)
    assert result['gaps']
    saved = next(iter(next(iter(repo.require_run('r')['state']['adaptiveAssessment']['scopes'].values())).values()))
    assert set(saved['candidateEvidenceIds']) == {output['evidenceId'], backlog['evidenceId']}
    added = evidence('The previous state is initialization.', 3)
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'evidence': [output, backlog, added]}})
    captured = []
    def second(rid, node, prompt, options):
        assert len(prompt.encode('utf8')) <= cap
        captured.extend(rows(prompt))
        assert rows(prompt)[0]['evidenceId'] == added['evidenceId']
        assert all(row['criterionId'] == 'input' for row in rows(prompt))
        return verdicts(prompt)
    assert run(repo, second)['stop_reason'] == 'covered'
    assert captured and backlog in repo.require_run('r')['state']['evidence']
    assert run(repo, lambda *_: pytest.fail('No repeated confirmed request'))['stop_reason'] == 'covered'


def routed_store(tmp_path):
    repo, first = store(tmp_path, evidenceCoverageContractVersion=3)
    second = evidence('A second passage states both the input role and the resulting output.', 2)
    first['obligationIds'] = ['left']; second['obligationIds'] = ['right']
    plan = [{'itemId': 'i', 'question': 'Explain both roles', 'obligations': [
        {'obligationId': oid, 'question': f'Explain {oid}', 'requiredSources': ['paper'],
         'completionCriteria': [{'criterionId': 'role', 'requirement': f'Explain {oid}', 'responseType': 'explanation'}]}
        for oid in ('left', 'right')]}]
    repo.update_run('r', lambda r: {**r, 'state': {**r['state'], 'plan': plan, 'evidence': [first, second]}})
    return repo, first, second


def test_query_routes_prioritize_candidates_but_never_establish_support_or_drop_cross_links(tmp_path, monkeypatch):
    repo, first, second = routed_store(tmp_path)
    record = repo.require_run('r')
    obligations = {o['obligationId']: o for item in record['state']['plan'] for o in item['obligations']}
    pairs = assessment._pairs(record, obligations)
    # Fit the two intended differently sized passages, not two copies of the
    # shorter first passage. Keep the assertions about routing and open gaps.
    selected = [{**pairs[index], 'pairId': f'R{i+1}'} for i, index in enumerate((0, 3))]
    cap = len(assessment._prompt(selected).encode('utf8')) + 1
    monkeypatch.setattr(assessment, '_input_limit', lambda _: cap)
    captured = []
    def reject(rid, node, prompt, opts):
        captured.extend((r['evidenceId'], r['obligationId']) for r in rows(prompt))
        return {'content': json.dumps([{'pairId': r['pairId'], 'relevant': False} for r in rows(prompt)])}
    assert run(repo, reject)['gaps']
    assert captured == [(first['evidenceId'], 'left'), (second['evidenceId'], 'right')]
    later = []
    def next_window(rid, node, prompt, opts):
        later.extend((r['evidenceId'], r['obligationId']) for r in rows(prompt))
        return {'content': json.dumps([{'pairId': r['pairId'], 'relevant': False} for r in rows(prompt)])}
    assert run(repo, next_window, {'run_id': 'r', 'requery_count': 1})['gaps']
    assert set(later) == {(first['evidenceId'], 'right'), (second['evidenceId'], 'left')}


@pytest.mark.parametrize('mutation', ['missing_pool', 'wrong_digest', 'duplicate', 'foreign_selected'])
def test_candidate_identity_corruption_stops_before_any_new_send(tmp_path, mutation):
    repo, _ = store(tmp_path, evidenceCoverageContractVersion=3)
    run(repo, lambda rid, node, prompt, opts: verdicts(prompt))
    def alter(record):
        journal = record['state']['adaptiveAssessment']
        saved = next(iter(next(iter(journal['scopes'].values())).values()))
        if mutation == 'missing_pool': saved.pop('candidateEvidenceIds')
        elif mutation == 'wrong_digest': saved['candidateEvidenceDigest'] = 'bad'
        elif mutation == 'duplicate': saved['candidateEvidenceIds'] *= 2
        else:
            saved['candidateEvidenceIds'] = ['foreign']
            from services.deep_research.contracts import digest
            saved['candidateEvidenceDigest'] = digest(saved['candidateEvidenceIds'])
        return record
    repo.update_run('r', alter)
    invoke = Mock()
    with pytest.raises(DeepResearchError, match='候选身份'): run(repo, invoke)
    invoke.assert_not_called()


def test_unknown_fresh_request_remains_frozen_and_is_not_reissued(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    repo, _ = store(tmp_path, evidenceCoverageContractVersion=3)
    provider = Mock(); provider.invoke.side_effect = LLMProviderError('unknown', provider='fixture', model='fixture')
    invoke = TrackedLLMInvoker(provider, repo.reserve_call, repo.complete_call)
    with pytest.raises(LLMProviderError): run(repo, invoke)
    before = deepcopy(repo.require_run('r')['state']['adaptiveAssessment'])
    with pytest.raises(UnknownCallError): run(repo, invoke)
    assert provider.invoke.call_count == 1
    assert repo.require_run('r')['state']['adaptiveAssessment'] == before


def test_saved_contract_two_keeps_legacy_window_without_new_identity_fields(tmp_path):
    repo, _ = store(tmp_path, evidenceCoverageContractVersion=2)
    assert run(repo, lambda rid, node, prompt, opts: verdicts(prompt))['gaps']
    saved = next(iter(next(iter(repo.require_run('r')['state']['adaptiveAssessment']['scopes'].values())).values()))
    assert 'candidateEvidenceIds' not in saved and 'candidateEvidenceDigest' not in saved
    assert run(repo, lambda *_: pytest.fail('Legacy replay must be GET-only'))['gaps']
