import copy
import json
from unittest.mock import patch

import pytest

from services.deep_research.design_completion import prepare_design_completion
from services.deep_research.experimental_reasoning import DESIGN_ROLES
from services.deep_research.repair import repair_rejected
from services.deep_research.coverage_repair import merge_verified_revisions
from services.deep_research.verification import verify_claims


def inputs():
    claims = [{'claimId': role, 'text': 'Proposed design.', 'kind': 'proposal',
               'designRole': role, 'designContractVersion': 2, 'evidenceRefs': ['e'],
               'obligationIds': ['o']} for role in DESIGN_ROLES if role not in {'steps', 'budget', 'limits'}]
    # A fact marked as a design role is not silently turned into a proposal.
    claims.append({'claimId': 'bad-fact', 'text': 'A reported fact.', 'kind': 'inference',
                   'designRole': 'limits', 'evidenceRefs': ['e'], 'obligationIds': ['o']})
    check = {'accepted': [dict(c, verification='proposal') for c in claims[:-1]],
             'rejected': [{'claimId': 'bad-fact', 'reason': 'invalid_design_role'}]}
    evidence = [{'evidenceId': 'e', 'sourceWorkId': 'paper', 'sourceVersionId': 'v1',
                 'accessLevel': 'fulltext', 'quote': 'The experiment has a fixed baseline.',
                 'obligationIds': ['o'], 'verification': {'literal': 'passed'}}]
    plan = [{'obligations': [{'obligationId': 'o'}]}]
    return {'claims': claims}, check, evidence, plan


def test_missing_roles_get_stable_rejected_slots_without_reclassifying_facts():
    report, verification, evidence, plan = inputs()
    original = copy.deepcopy((report, verification, evidence, plan))
    draft, checked = prepare_design_completion(report, verification, evidence, plan)
    slots = draft['claims'][len(report['claims']):]
    assert [c['designRole'] for c in slots] == ['budget', 'steps', 'limits']
    assert all(c['text'] == '' and c['kind'] == 'proposal' for c in slots)
    assert checked['accepted'] == verification['accepted']
    assert checked['rejected'][0] == verification['rejected'][0]
    assert draft['claims'][:len(report['claims'])] == report['claims']
    assert (report, verification, evidence, plan) == original
    assert prepare_design_completion(draft, checked, evidence, plan) == (draft, checked)


def test_ambiguous_unverified_or_unrelated_evidence_cannot_authorize_slots():
    report, verification, evidence, plan = inputs()
    for rows in [[], evidence * 2, [dict(evidence[0], obligationIds=['other'])],
                 [dict(evidence[0], accessLevel='abstract')],
                 [dict(evidence[0], verification={'literal': 'failed'})]]:
        assert prepare_design_completion(report, verification, rows, plan) == (report, verification)


def test_existing_rejected_role_is_repaired_in_place_and_ids_do_not_collide():
    report, verification, evidence, plan = inputs()
    report['claims'].append({'claimId': 'design_completion_budget', 'kind': 'proposal',
                             'designRole': 'steps', 'text': 'Incomplete steps.'})
    verification['rejected'].append({'claimId': 'design_completion_budget', 'reason': 'incomplete'})
    draft, checked = prepare_design_completion(report, verification, evidence, plan)
    slots = draft['claims'][len(report['claims']):]
    assert [c['designRole'] for c in slots] == ['budget', 'limits']
    assert slots[0]['claimId'] == 'design_completion_budget_new'
    assert len({c['claimId'] for c in draft['claims']}) == len(draft['claims'])


def test_new_slot_requires_repair_validation_and_independent_verification():
    report, verification, evidence, plan = inputs()
    draft, checked = prepare_design_completion(report, verification, evidence, plan)
    slot = next(c for c in draft['claims'] if c['claimId'] == 'design_completion_limits')
    revised = dict(slot, text='This is a proposed diagnostic only; it cannot establish generalization.',
                   evidenceRefs=['E1'])
    calls = []
    def invoke(prompt):
        calls.append(prompt)
        assert 'server-allocated slots' in prompt
        return {'content': json.dumps([revised])}
    result = repair_rejected(draft, checked, evidence, 'Design an experiment.', invoke, json.loads)
    assert len(result) == len(calls) == 1
    assert result[0]['evidenceRefs'] == ['e']
    assert result[0]['designContractVersion'] == 2
    assert not verify_claims(result, evidence)['accepted']
    assert merge_verified_revisions(checked, verify_claims(result, evidence))['accepted'] == checked['accepted']
    # Only a separately accepted registered ID can enter the final report.
    accepted = dict(result[0], verification='proposal')
    merged = merge_verified_revisions(checked, {'accepted': [accepted], 'rejected': []})
    assert accepted in merged['accepted']
    assert not any(r['claimId'] == accepted['claimId'] for r in merged['rejected'])
    for update in [{'claimId': 'invented'}, {'kind': 'reported'}, {'designRole': 'metrics'},
                   {'evidenceRefs': ['foreign']}]:
        assert repair_rejected(draft, checked, evidence, 'Design an experiment.',
            lambda _: {'content': json.dumps([{**revised, **update}])}, json.loads) == []


@pytest.mark.parametrize('resume,rejected', [(False, False), (False, True), (True, False)])
def test_graph_checks_registered_slots_and_resumes_without_resending_repair(resume, rejected):
    from services.deep_research.graph import make_verify_node

    report, verification, evidence, plan = inputs()
    record = {'question': 'Design an experiment.', 'state': {
        'reportBody': copy.deepcopy(report), 'evidence': evidence, 'plan': plan,
        'outputKind': 'experiment_design'}}
    repair_calls, checks = [], []

    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record

    def invoke(run, node, prompt, options):
        assert node == 'repair_claims'
        repair_calls.append(prompt)
        slots = record['state']['repairReport']['claims'][len(report['claims']):]
        assert {c['designRole'] for c in slots} == {'budget', 'steps', 'limits'}
        return {'content': json.dumps([
            {**c, 'text': 'Explicit prospective design content.', 'evidenceRefs': ['E1']}
            for c in slots])}

    class SimulatedInterruption(Exception):
        pass

    def verify(claims, sources, semantic):
        if claims == report['claims']:
            return copy.deepcopy(verification)
        checks.append(copy.deepcopy(claims))
        assert {c['claimId'] for c in claims} == {
            'design_completion_budget', 'design_completion_steps', 'design_completion_limits'}
        assert all(c['evidenceRefs'] == ['e'] for c in claims)
        if resume and len(checks) == 1:
            # The response and its allowed identities have already been checkpointed.
            assert record['state']['repairDraft'] == claims
            raise SimulatedInterruption()
        return {'accepted': [] if rejected else [dict(c, verification='proposal') for c in claims],
                'rejected': [{'claimId': c['claimId'], 'reason': 'semantic_unresolved'}
                             for c in claims] if rejected else []}

    node = make_verify_node(verify, None, update, invoke)
    with patch('services.deep_research.final_coverage.audit_final_answer',
               return_value={'status': 'not_checked', 'gaps': []}):
        if resume:
            with pytest.raises(SimulatedInterruption):
                node({'run_id': 'r'})
            assert record['state']['repairAttempted']
        node({'run_id': 'r'})
        # Re-entering a completed verification must not issue another repair.
        node({'run_id': 'r'})
    assert len(repair_calls) == 1
    assert len(checks) == (2 if resume else 1)
    assert record['state']['reportBody'] == report
    published = record['state']['verifiedReport']['verifiedClaims']
    assert len(published) == len(verification['accepted']) + (0 if rejected else 3)
    assert not any(c['claimId'] == 'bad-fact' for c in published)
    assert all(c['text'] for c in published)
    independent = record['state']['repairVerificationChecks']
    assert len(independent['accepted']) == (0 if rejected else 3)
    assert len(independent['rejected']) == (3 if rejected else 0)
