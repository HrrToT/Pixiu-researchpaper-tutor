from copy import deepcopy
import json

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.execution_spec import EXECUTION_SPEC_CONTRACT, execution_spec_contract_for_roles
from services.deep_research.repair import repair_rejected
from services.deep_research.repair_batches import split_repair_targets
from services.deep_research.repair_prompt import factor_design_deliverables
from services.deep_research.experimental_reasoning import DESIGN_ROLES


def inputs():
    roles = [('data', 'data'), ('budget', 'budget'), ('h', 'hypothesis'),
             ('a', 'analysis'), ('steps', 'steps')]
    claims = [{'claimId': identity, 'kind': 'proposal', 'designRole': role,
               'text': f'Original {identity}.', 'evidenceRefs': []} for identity, role in roles]
    return {'claims': claims}, {'accepted': [], 'rejected': [
        {'claimId': c['claimId'], 'reason': 'incomplete'} for c in claims]}


def fake_preparer(monkeypatch, limit_failure=None):
    """Control capacity only; use the real output parser and public scheduler."""
    def prepare(report, verification, evidence, question, **kwargs):
        ids = [r['claimId'] for r in verification['rejected']]
        if len(ids) > 2 or (limit_failure and limit_failure in ids):
            raise BudgetExhaustedError('repairEvidenceBytes', 24000, 25000)
        return {'prompt': json.dumps({'targets': ids, 'context': kwargs['draft_context']}),
                'originals': {c['claimId']: c for c in report['claims'] if c['claimId'] in ids},
                'aliases': {}, 'allowed': {identity: [] for identity in ids}}
    monkeypatch.setattr('services.deep_research.repair._prepare_repair', prepare)


def response(prompt):
    return {'content': json.dumps([{'claimId': identity, 'kind': 'proposal',
        'text': f'Revised {identity}.', 'evidenceRefs': []}
        for identity in json.loads(prompt)['targets']])}


def test_scheduler_keeps_all_hypotheses_and_analyses_atomic_and_each_target_once():
    report, _ = inputs()
    groups = split_repair_targets(report['claims'])
    assert groups == [['data', 'budget'], ['h', 'a'], ['steps']]
    assert sorted(cid for group in groups for cid in group) == sorted(c['claimId'] for c in report['claims'])


def test_all_batches_preflight_before_any_provider_send(monkeypatch):
    report, verification = inputs()
    fake_preparer(monkeypatch, limit_failure='steps')
    sends, snapshots = [], []
    with pytest.raises(BudgetExhaustedError):
        repair_rejected(report, verification, [], 'Question', sends.append, json.loads,
                        checkpoint=snapshots.append)
    assert sends == snapshots == []


def test_unknown_pending_batch_propagates_and_completed_batch_is_not_resent(monkeypatch):
    report, verification = inputs()
    fake_preparer(monkeypatch)
    saved, sent = [], []
    class Unknown(Exception):
        pass
    def invoke(prompt):
        sent.append(json.loads(prompt))
        if len(sent) == 2:
            raise Unknown('Outcome unresolved')
        return response(prompt)
    with pytest.raises(Unknown):
        repair_rejected(report, verification, [], 'Question', invoke, json.loads, checkpoint=saved.append)
    assert set(saved[-1]['results']) == {'0'}
    original = deepcopy(saved[-1])
    resumed = []
    result = repair_rejected(report, verification, [], 'Question',
        lambda prompt: (resumed.append(json.loads(prompt)) or response(prompt)), json.loads,
        batch_state=original, checkpoint=saved.append)
    # Scheduler resumes the pending batch; production tracked invoker, covered
    # separately, blocks an unresolved call rather than issuing it again.
    assert [p['targets'] for p in resumed] == [['h', 'a'], ['steps']]
    assert any(c['text'] == 'Revised data.' for c in resumed[0]['context'])
    assert len(result) == 5 and original == saved[1]


def test_budget_exhaustion_keeps_completed_drafts_without_retry(monkeypatch):
    report, verification = inputs()
    fake_preparer(monkeypatch)
    sent, saved = [], []
    def invoke(prompt):
        sent.append(prompt)
        if len(sent) == 2:
            raise BudgetExhaustedError('tokens', 100, 101)
        return response(prompt)
    result = repair_rejected(report, verification, [], 'Question', invoke, json.loads, checkpoint=saved.append)
    assert [c['claimId'] for c in result] == ['data', 'budget']
    assert len(sent) == 2 and set(saved[-1]['results']) == {'0'}


def test_truncated_batch_is_final_empty_result_and_never_resubmitted(monkeypatch):
    report, verification = inputs()
    fake_preparer(monkeypatch)
    saved = []
    repair_rejected(report, verification, [], 'Question',
        lambda prompt: {'content': response(prompt)['content'], 'finishReason': 'length'},
        json.loads, checkpoint=saved.append)
    def forbidden(_):
        raise AssertionError('Settled truncated responses must not be regenerated')
    assert repair_rejected(report, verification, [], 'Question', forbidden, json.loads,
                           batch_state=saved[-1]) == []


def test_changed_repair_input_rejects_saved_plan_before_send(monkeypatch):
    report, verification = inputs()
    fake_preparer(monkeypatch)
    saved = []
    repair_rejected(report, verification, [], 'Question', response, json.loads, checkpoint=saved.append)
    with pytest.raises(DeepResearchError, match='原始输入'):
        repair_rejected(report, verification, [], 'Changed question', lambda _: pytest.fail('send'),
                        json.loads, batch_state=saved[-1])


def test_role_schema_selection_is_exact_and_retains_every_common_constraint():
    assert execution_spec_contract_for_roles({'groups', 'data', 'analysis'}) == EXECUTION_SPEC_CONTRACT
    selected = execution_spec_contract_for_roles({'data'})
    assert 'data role:' in selected and 'groups role:' not in selected and 'analysis role:' not in selected
    assert 'executionSpec schemas' in selected and 'Do not invent availability' in selected
    assert 'subset with its parent dataset' in selected


def test_only_exact_duplicate_role_requirements_are_factored_losslessly():
    claims = [{'claimId': 'data', 'designRole': 'data'}, {'claimId': 'other', 'designRole': 'data'}]
    checks = {'data': {'reason': 'missing_design_deliverable', 'detail': DESIGN_ROLES['data'][1]},
              'other': {'reason': 'semantic_unresolved', 'detail': 'Different omitted requirement'}}
    before = deepcopy(checks)
    packed = factor_design_deliverables(checks, claims, DESIGN_ROLES)
    role = packed['data'].pop('detailRequirementRole')
    packed['data']['detail'] = DESIGN_ROLES[role][1]
    assert packed == checks == before


def test_required_context_is_kept_or_single_target_stops_before_send():
    claim = {'claimId': 'c', 'kind': 'reported', 'text': 'Original fact.', 'evidenceRefs': ['e']}
    evidence = [{'evidenceId': 'e', 'quote': 'Exact fact.', 'sourceContext': 'Background. ' * 1000 + 'Exact fact.'}]
    sends = []
    with pytest.raises(BudgetExhaustedError):
        repair_rejected({'claims': [claim]}, {'rejected': [{'claimId': 'c'}]}, evidence, '',
                        sends.append, json.loads, max_prompt_bytes=3500)
    assert not sends


def test_real_ledger_blocks_unknown_pending_batch_on_resume(monkeypatch, tmp_path):
    from llm.provider import LLMResult, LLMUsage, LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    report, verification = inputs()
    fake_preparer(monkeypatch)
    repo = DeepResearchRepository(str(tmp_path / 'calls.sqlite3'))
    repo.initialize()
    repo.create_run({'runId': 'r'})
    repo.begin_execution('r')
    sent, saved = [], []
    class Provider:
        def invoke(self, request):
            sent.append(request.prompt)
            if len(sent) == 2:
                raise LLMProviderError('Unknown outcome', provider='fixture', model='fixture')
            return LLMResult('fixture', 'fixture', response(request.prompt)['content'], LLMUsage(8, 2, 10), 'stop')
    tracked = TrackedLLMInvoker(Provider(), repo.reserve_call, repo.complete_call)
    def invoke(prompt):
        return tracked('r', 'repair_claims', prompt, {'max_tokens': 3000})
    with pytest.raises(LLMProviderError):
        repair_rejected(report, verification, [], 'Question', invoke, json.loads, checkpoint=saved.append)
    with pytest.raises(UnknownCallError):
        repair_rejected(report, verification, [], 'Question', invoke, json.loads, batch_state=saved[-1])
    assert len(sent) == 2
    assert [c['status'] for c in repo.list_calls('r')] == ['succeeded', 'unknown']


def test_completed_batch_checkpoint_survives_real_database_reopen(monkeypatch, tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    report, verification = inputs()
    fake_preparer(monkeypatch)
    database = str(tmp_path / 'checkpoints.sqlite3')
    repo = DeepResearchRepository(database)
    repo.initialize()
    repo.create_run({'runId': 'r'})
    sends = []
    def checkpoint(state):
        repo.update_run('r', lambda run: {**run, 'state': {'repairBatchState': state}})
    def invoke(prompt):
        sends.append(json.loads(prompt)['targets'])
        if len(sends) == 2:
            raise InterruptedError('Stopped between batches')
        return response(prompt)
    with pytest.raises(InterruptedError):
        repair_rejected(report, verification, [], 'Question', invoke, json.loads, checkpoint=checkpoint)
    reopened = DeepResearchRepository(database)
    reopened.initialize()
    saved = reopened.require_run('r')['state']['repairBatchState']
    pending = []
    result = repair_rejected(report, verification, [], 'Question',
        lambda prompt: (pending.append(json.loads(prompt)['targets']) or response(prompt)),
        json.loads, batch_state=saved)
    assert pending == [['h', 'a'], ['steps']] and len(result) == 5


def test_real_prompt_splits_required_sources_and_restores_local_aliases():
    claims = [{'claimId': key, 'kind': 'reported', 'text': 'Original fact.', 'evidenceRefs': [key]}
              for key in ('a', 'b', 'c')]
    evidence = [{'evidenceId': key, 'quote': key + ' exact passage ' * 700} for key in ('a', 'b', 'c')]
    sent, saved = [], []
    def invoke(prompt):
        targets = json.JSONDecoder().raw_decode(prompt.split('Rejected claims and checks:\n', 1)[1])[0]
        rows = json.JSONDecoder().raw_decode(prompt.split('Exact available evidence:\n', 1)[1])[0]
        assert len(prompt.encode('utf-8')) <= 24000 and len(rows) == 1
        target = targets[0]['claim']
        assert len(targets) == 1 and target['evidenceRefs'] == ['E1']
        sent.append(target['claimId'])
        assert rows[0]['quote'] == next(e['quote'] for e in evidence if e['evidenceId'] == target['claimId'])
        return {'content': json.dumps([{**target, 'text': 'Revised fact.', 'evidenceRefs': ['E1']},
                                     {**target, 'claimId': 'other_batch', 'evidenceRefs': ['E1']}])}
    result = repair_rejected({'claims': claims}, {'accepted': [], 'rejected': [
        {'claimId': c['claimId']} for c in claims]}, evidence, 'Question', invoke, json.loads, checkpoint=saved.append)
    assert sent == ['a', 'b', 'c']
    assert [(c['claimId'], c['evidenceRefs']) for c in result] == [(key, [key]) for key in ('a', 'b', 'c')]
