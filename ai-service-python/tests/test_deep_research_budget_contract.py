import copy
import json
from unittest.mock import patch, Mock

import pytest

from services.deep_research.budget_contract import stamp_budget_contract, enforce_budget_consistency
from services.deep_research.design_completion import prepare_design_completion
from services.deep_research.design_audit import validate_design_audit
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.graph import make_verify_node, make_publish_node, make_synthesize_node
from services.deep_research.repair import repair_rejected
from services.deep_research.verification import verify_claims


def budget_spec(groups=None):
    return {'baseline': {'mode': 'train', 'unit': 'optimizer_steps', 'maxBudget': 30000,
                         'stoppingRule': 'Stop at the iteration cap.'},
            'recovery': {'mode': 'matched', 'unit': 'optimizer_steps',
                         'groups': groups or {'00': 1000, '01': 1000, '10': 1000, '11': 1000}}}


def group_spec(count=2):
    return {'factors': [{'name': str(i), 'control': {'action': 'Leave unchanged.', 'parameters': []},
                         'treatment': {'action': 'Apply intervention.', 'parameters': []}}
                        for i in range(count)]}


def claim(identity, role, spec=None, marked=False):
    result = {'claimId': identity, 'kind': 'proposal', 'designRole': role,
              'designContractVersion': 2, 'text': 'Proposed ' + role, 'evidenceRefs': []}
    if spec is not None:
        result['executionSpec'] = spec
    if marked:
        result['budgetContractVersion'] = 1
    return result


def test_new_budget_is_checked_before_semantics_and_legacy_marker_is_not_added_implicitly():
    old = claim('b', 'budget', {'recoveryBudget': 1000})
    checker = Mock(side_effect=lambda claims, evidence:
                   [{'claimId': c['claimId'], 'status': 'passed'} for c in claims])
    assert verify_claims([old], [], checker)['accepted']
    old_copy = copy.deepcopy(old)
    report = stamp_budget_contract({'claims': [old]})
    assert old == old_copy and 'budgetContractVersion' not in old
    checker.reset_mock()
    assert verify_claims(report['claims'], [], checker)['rejected'][0]['reason'] == 'incomplete_budget_spec'
    checker.assert_not_called()
    invalid = claim('b', 'budget', budget_spec({'00': 0, '01': 1000, '10': 1000, '11': 1000}), True)
    assert verify_claims([invalid], [], checker)['accepted'] == []
    checker.assert_not_called()


def test_budget_mapping_and_single_canonical_definition_gate_only_marked_budgets():
    groups, budget = claim('g', 'groups', group_spec()), claim('b', 'budget', budget_spec(), True)
    accepted = [dict(groups, verification='proposal'), dict(budget, verification='proposal')]
    original = {'accepted': accepted, 'rejected': []}
    assert enforce_budget_consistency(original) == original
    for rows in [[budget], [claim('g', 'groups', group_spec(1)), budget],
                 [groups, budget, dict(budget, claimId='second')]]:
        checked = enforce_budget_consistency({'accepted': rows, 'rejected': []})
        assert not any(c.get('budgetContractVersion') == 1 for c in checked['accepted'])
        assert all(c['reason'] == 'inconsistent_budget_groups' for c in checked['rejected'])
    assert original == {'accepted': accepted, 'rejected': []}
    legacy = claim('legacy', 'budget', {'unknownShape': 7})
    assert enforce_budget_consistency({'accepted': [legacy], 'rejected': []})['accepted'] == [legacy]


def test_budget_protocol_is_visible_once_and_original_contradictory_prose_is_retained():
    budget = claim('b', 'budget', budget_spec(), True)
    budget['text'] = 'The baseline has zero recovery; this contradicts the typed matched budget.'
    original = copy.deepcopy(budget)
    rendered = materialize_execution_claim(budget)
    assert rendered['text'].startswith(budget['text'])
    assert '1000' in rendered['text'] and '00' in rendered['text']
    assert materialize_execution_claim(rendered) == rendered
    assert verification_claim_view(rendered) == budget
    assert budget == original


def test_budget_audit_only_accepts_real_typed_fields_from_valid_marked_budget():
    budget = claim('b', 'budget', budget_spec(), True)
    binding = {'claimId': 'b', 'path': ['executionSpec', 'recovery', 'groups'],
               'value': budget['executionSpec']['recovery']['groups']}
    verdict = {'designAudit': {'per_group_steps': {'fields': [binding]}}}
    assert validate_design_audit(budget, verdict, []) == []
    for changed in [dict(budget, budgetContractVersion=None),
                    dict(budget, executionSpec=budget_spec({'00': 0, '01': 1000, '10': 1000, '11': 1000}))]:
        assert validate_design_audit(changed, verdict, []) == ['per_group_steps']
    foreign = copy.deepcopy(verdict)
    foreign['designAudit']['per_group_steps']['fields'][0]['path'][1] = 'invented'
    assert validate_design_audit(budget, foreign, []) == ['per_group_steps']


def test_missing_budget_slot_and_repair_preserve_server_budget_contract_marker():
    report = stamp_budget_contract({'claims': []})
    evidence = [{'evidenceId': 'e', 'sourceWorkId': 'paper', 'sourceVersionId': 'v1',
                 'accessLevel': 'fulltext', 'obligationIds': ['o'], 'verification': {'literal': 'passed'}}]
    draft, checked = prepare_design_completion(report, {'accepted': [], 'rejected': []}, evidence,
                                               [{'obligations': [{'obligationId': 'o'}]}])
    slot = next(c for c in draft['claims'] if c['designRole'] == 'budget')
    assert slot['budgetContractVersion'] == 1
    revised = dict(slot, text='A prospective matched budget.', executionSpec=budget_spec(), evidenceRefs=[])
    revised.pop('budgetContractVersion')
    result = repair_rejected(draft, checked, evidence, 'Design an experiment.',
                             lambda _: {'content': json.dumps([revised])}, json.loads)
    assert result[0]['budgetContractVersion'] == 1
    assert '1000' in result[0]['text']


def test_graph_rejects_independently_passed_repair_with_wrong_group_mapping():
    groups, budget = claim('g', 'groups', group_spec()), claim('b', 'budget', marked=True)
    record = {'question': 'Design an experiment.', 'state': {'reportBody': {'claims': [groups, budget]}, 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def semantic(claims, evidence):
        return [{'claimId': c['claimId'], 'status': 'passed'} for c in claims]
    wrong = claim('b', 'budget', budget_spec({'0': 1000, '1': 1000}))
    def invoke(run, node, prompt, options):
        assert node == 'repair_claims'
        return {'content': json.dumps([wrong])}
    with patch('services.deep_research.final_coverage.audit_final_answer',
               return_value={'status': 'not_checked', 'gaps': []}):
        make_verify_node(verify_claims, semantic, update, invoke)({'run_id': 'r'})
    verified = record['state']['verifiedReport']
    assert [c['claimId'] for c in verified['verifiedClaims']] == ['g']
    assert any(c['claimId'] == 'b' and c['reason'] == 'inconsistent_budget_groups'
               for c in verified['rejectedClaims'])


def test_resumed_publish_checks_marked_budget_and_invalidates_stale_coverage():
    groups = dict(claim('g', 'groups', group_spec(1)), verification='proposal')
    budget = dict(claim('b', 'budget', budget_spec(), True), verification='proposal')
    record = {'state': {'outputKind': 'experiment_design', 'verifiedReport': {
        'verifiedClaims': [groups, budget], 'rejectedClaims': [],
        'answerCoverage': {'status': 'checked', 'gaps': []}}}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r'})
    assert result['outcome'] == 'partial'
    assert [c['claimId'] for c in publish.call_args.kwargs['payload']['claims']] == ['g']
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_design_contract'


@pytest.mark.parametrize('enabled', [False, True])
def test_run_snapshot_controls_budget_contract_and_model_cannot_select_version(enabled):
    budget = claim('b', 'budget', budget_spec())
    budget['budgetContractVersion'] = 999
    record = {'question': 'Design an experiment.', 'state': {
        'outputKind': 'experiment_design', 'metricDomains': ['quality'], 'evidence': [], 'plan': []}}
    if enabled:
        record['budgetContractVersion'] = 1
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(run, node, prompt, options, **kwargs):
        assert node == 'synthesize'
        assert ('Budget role executionSpec' in prompt) is enabled
        return {'content': json.dumps({'budgetContractVersion': 999, 'claims': [budget]})}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    report = record['state']['reportBody']
    if enabled:
        assert report['budgetContractVersion'] == report['claims'][0]['budgetContractVersion'] == 1
        assert '1000' in report['claims'][0]['text']
    else:
        assert 'budgetContractVersion' not in report
        assert 'budgetContractVersion' not in report['claims'][0]
        assert report['claims'][0]['text'] == budget['text']
