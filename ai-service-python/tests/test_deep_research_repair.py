import json
import threading

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.repair import repair_rejected
from services.deep_research.verification import verify_claims


def test_repair_cannot_widen_identity_evidence_or_disguise_fact_as_proposal():
    original = {'claimId': 'c', 'kind': 'reported', 'text': '999 FPS', 'evidenceRefs': ['e']}
    verification = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'numeric_mismatch'}]}
    calls = []
    def invoke(prompt):
        calls.append(prompt)
        return {'content': json.dumps([
            {**original, 'kind': 'proposal'},
            {**original, 'claimId': 'new'},
            {**original, 'evidenceRefs': ['foreign']},
        ])}
    assert repair_rejected({'claims': [original]}, verification, [], '核查', invoke, json.loads) == []
    assert len(calls) == 1


def test_repaired_wording_must_pass_numeric_and_semantic_checks_again():
    original = {'claimId': 'c', 'kind': 'reported', 'text': '999 FPS', 'evidenceRefs': ['e']}
    check = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'numeric_mismatch'}]}
    evidence = [{'evidenceId': 'e', 'quote': '200 FPS', 'verification': {'literal': 'passed'}}]
    revised = repair_rejected({'claims': [original]}, check, evidence, '核查，100字以内',
        lambda p: {'content': json.dumps([{**original, 'text': '速度为200 FPS', 'conditions': '本次评测'}])}, json.loads)
    assert revised[0]['conditions'] == {'context': '本次评测'}
    assert not verify_claims(revised, evidence)['accepted']
    assert verify_claims(revised, evidence, lambda c, e: [{'claimId': 'c', 'status': 'passed'}])['accepted']
    overlong = lambda p: {'content': json.dumps([{**original, 'text': 'x' * 101}])}
    assert repair_rejected({'claims': [original]}, check, evidence, '100字以内', overlong, json.loads) == []


def test_repair_stops_when_normal_budget_is_exhausted():
    def exhausted(_):
        raise BudgetExhaustedError('modelCalls', 15, 15)
    original = {'claimId': 'c', 'kind': 'reported', 'text': 'bad', 'evidenceRefs': []}
    assert repair_rejected({'claims': [original]}, {'rejected': [{'claimId': 'c'}]}, [], '', exhausted, json.loads) == []


def test_repair_short_ids_restore_claim_and_cell_identity_without_mutating_input():
    original = {'claimId': 'c', 'kind': 'reported', 'text': 'FPS 200', 'evidenceRefs': ['ev_full_identity']}
    evidence = [{'evidenceId': 'ev_full_identity', 'quote': 'FPS 200'}]
    def invoke(prompt):
        assert '"evidenceRefs": ["E1"]' in prompt
        assert '"value":"200"' in prompt
        return {'content': json.dumps([{**original, 'evidenceRefs': ['E1'], 'tableBindings': [
            {'evidenceId': 'E1', 'rowNumber': 1, 'groupIndex': 0, 'metric': 'FPS', 'value': '200'}]}])}
    revised = repair_rejected({'claims': [original]}, {'rejected': [{'claimId': 'c'}]}, evidence, '', invoke, json.loads)
    assert revised[0]['evidenceRefs'] == ['ev_full_identity']
    assert revised[0]['tableBindings'][0]['evidenceId'] == 'ev_full_identity'
    assert original == {'claimId': 'c', 'kind': 'reported', 'text': 'FPS 200', 'evidenceRefs': ['ev_full_identity']}
    assert evidence == [{'evidenceId': 'ev_full_identity', 'quote': 'FPS 200'}]


def test_repair_rejects_length_finish_even_if_partial_content_is_valid_json():
    original = {'claimId': 'c', 'kind': 'reported', 'text': 'partial', 'evidenceRefs': []}
    def must_not_parse(_):
        raise AssertionError('truncated provider output must not be salvaged')
    assert repair_rejected({'claims': [original]}, {'rejected': [{'claimId': 'c'}]}, [], '',
        lambda p: {'content': json.dumps([original]), 'finishReason': 'length'}, must_not_parse) == []


def test_repair_normalizes_only_unambiguous_claim_text_alias_and_still_rechecks():
    original = {'claimId': 'c', 'kind': 'reported', 'text': 'bad', 'evidenceRefs': ['e']}
    check = {'rejected': [{'claimId': 'c'}]}
    evidence = [{'evidenceId': 'e', 'quote': '200 FPS', 'verification': {'literal': 'passed'}}]
    response = {k: v for k, v in original.items() if k != 'text'}
    response['claim'] = '200 FPS'
    revised = repair_rejected({'claims': [original]}, check, evidence, '',
        lambda p: {'content': json.dumps([response])}, json.loads)
    assert revised[0]['text'] == '200 FPS' and 'claim' not in revised[0]
    assert not verify_claims(revised, evidence)['accepted']
    response['text'] = '999 FPS'
    assert repair_rejected({'claims': [original]}, check, evidence, '',
        lambda p: {'content': json.dumps([response])}, json.loads) == []


def test_selected_evidence_absence_is_still_subject_to_semantic_check():
    ev = {'evidenceId': 'e', 'quote': 'A limited passage.', 'verification': {'literal': 'passed'}}
    c = {'claimId': 'c', 'kind': 'inference', 'evidenceRefs': ['e'], 'text': '所选证据未提供硬件配置。'}
    assert not verify_claims([c], [ev])['accepted']
    assert verify_claims([c], [ev], lambda *_: [{'claimId': 'c', 'status': 'passed'}])['accepted']
    assert verify_claims([{**c, 'text': '论文未提供硬件配置。'}], [ev])['rejected'][0]['reason'] == 'absence_not_established'


def test_proposal_cannot_bypass_logical_verification():
    claim = {'claimId': 'p', 'kind': 'proposal', 'text': 'PSNR和LPIPS使用相同损失方向', 'evidenceRefs': []}
    result = verify_claims([claim], [], lambda c, e: [{'claimId': 'p', 'status': 'failed', 'reason': 'metric direction'}])
    assert not result['accepted'] and result['rejected'][0]['detail'] == 'metric direction'
    assert not verify_claims([claim], [])['accepted']


@pytest.mark.parametrize('exhausted,expected', [(True, 'skipped_budget'), (False, 'response_received')])
def test_repair_state_distinguishes_budget_skip_from_model_response(exhausted, expected):
    from services.deep_research.graph import make_verify_node
    original = {'claimId': 'c', 'kind': 'reported', 'text': 'bad', 'evidenceRefs': []}
    record = {'state': {'reportBody': {'claims': [original]}, 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(*args, **kwargs):
        if exhausted:
            raise BudgetExhaustedError('modelCalls', 13, 14)
        return {'content': '[]'}
    verify = lambda *args: {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'unsupported'}]}
    make_verify_node(verify, None, update, llm_invoke=invoke)({'run_id': 'r'})
    assert record['state']['repairStatus'] == expected
    assert record['state']['verifiedReport']['verificationSummary'] == {'accepted': 0, 'rejected': 1}


def test_capacity_rejects_before_clock_starts_and_does_not_queue_executor(tmp_path):
    repo = DeepResearchRepository(str(tmp_path / 'runs.sqlite3'))
    repo.initialize()
    facade = ResearchFacade(repo, lambda **kw: None, llm_client=object(), max_concurrent=1)
    entered, release = threading.Event(), threading.Event()
    def execute(run):
        entered.set()
        assert release.wait(5)
    facade._execute_graph = execute
    for run in ('a', 'b'):
        repo.create_run({'runId': run, 'taskId': 't'})
    try:
        facade._start_execution('a')
        assert entered.wait(2)
        with pytest.raises(DeepResearchError) as error:
            facade._action_resume('b', repo.require_run('b')['runRevision'], {})
        assert error.value.code == 'execution_capacity'
        assert repo.require_run('b')['status'] == 'queued'
        assert not repo.require_run('b').get('startedAt')
        assert set(facade._active_futures) == {'a'}
        worker = facade._active_futures['a']
        release.set()
        worker.result(timeout=3)
        facade._action_resume('b', repo.require_run('b')['runRevision'], {})
        assert repo.require_run('b')['status'] == 'running'
    finally:
        release.set()
        facade.shutdown()


def test_elapsed_time_is_visible_for_failure_and_freezes_while_waiting():
    from services.deep_research.facade import _elapsed_seconds
    value = {'status': 'failed', 'startedAt': '2026-10-12T00:00:00Z',
             'finishedAt': '2026-10-12T00:01:04Z', 'budget': {'elapsedSeconds': 0}}
    assert _elapsed_seconds(value) == 64
    value.update(status='waiting_user', state={'waitingSince': '2026-10-12T00:00:12Z'})
    assert _elapsed_seconds(value) == 12
