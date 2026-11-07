"""A proposed protocol cannot assume an ungrounded released checkpoint."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.asset_availability import validate_asset_availability, enforce_asset_prerequisites
from services.deep_research.coverage_repair import merge_verified_revisions
from services.deep_research.graph import make_publish_node
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims


def inputs():
    clause = 'Pre-trained models for the Synthetic benchmark are publicly available'
    quote = clause + ' at https://example.org/models.'
    claim = {'claimId': 'budget', 'kind': 'proposal', 'designRole': 'budget',
             'designContractVersion': 2, 'budgetContractVersion': 1,
             'text': 'Proposed use of the published Synthetic pretrained model, paired across groups.',
             'evidenceRefs': ['e'], 'executionSpec': {
                 'baseline': {'mode': 'existing', 'selectionRule': 'Select the Synthetic pretrained model.'},
                 'recovery': {'mode': 'matched', 'unit': 'optimizer_steps', 'groups': {'0': 1000, '1': 1000}}}}
    evidence = [{'evidenceId': 'e', 'quote': quote, 'accessLevel': 'fulltext',
                 'verification': {'literal': 'passed'}, 'sourceWorkId': 'paper', 'sourceVersionId': 'v1'}]
    audit = {'evidenceId': 'e', 'quote': quote, 'assetQuote': 'Pre-trained models',
             'availabilityQuote': clause, 'locator': 'https://example.org/models'}
    return claim, audit, evidence


def passed(claims, evidence):
    return [{'claimId': c['claimId'], 'status': 'passed'} for c in claims]


def dependent(role):
    return {'claimId': role, 'kind': 'proposal', 'designRole': role,
            'designContractVersion': 2, 'text': 'Proposed paired protocol on the shared baseline.',
            'evidenceRefs': []}


def test_bound_release_reference_passes_without_changing_source_or_claim():
    claim, audit, evidence = inputs()
    before = deepcopy((claim, audit, evidence))
    assert validate_asset_availability(claim, audit, evidence) == []
    assert (claim, audit, evidence) == before
    result = verify_claims([claim], evidence,
        lambda c, e: [{**passed(c, e)[0], 'assetAvailability': audit}])
    assert result['accepted'][0]['verification'] == 'proposal'
    assert result['accepted'][0]['assetAvailability'] == audit


@pytest.mark.parametrize('clause', ['Pretrained models are released',
                                  'We release our pretrained models',
                                  'Pre-trained models\nare publicly available',
                                  '预训练模型已公开'])
def test_common_release_spelling_and_pdf_line_wrap_keep_literal_source(clause):
    claim, audit, evidence = inputs()
    quote = clause + ' at https://example.org/models.'
    evidence[0]['quote'] = quote
    audit.update(quote=quote, availabilityQuote=clause, assetQuote=clause)
    assert validate_asset_availability(claim, audit, evidence) == []
    assert evidence[0]['quote'] == quote


@pytest.mark.parametrize('clause', [
    'We trained models on the Synthetic benchmark',
    'Checkpoints were trained for the Synthetic benchmark',
    'Code is available; pretrained models were trained on Synthetic',
    'Pre-trained models are not available',
    'No pretrained models are released',
    'Pre-trained models will be released',
    'Pre-trained models are going to be released',
    'If pretrained models are available',
    'Pre-trained models may be available',
    'Pre-trained models are available upon request',
    '预训练模型尚未公开',
    '预训练模型计划公开提供',
    '预训练模型会公开提供',
])
def test_training_code_release_or_qualified_availability_is_insufficient(clause):
    claim, audit, evidence = inputs()
    evidence[0]['quote'] = clause + ' at https://example.org/models.'
    audit.update(quote=evidence[0]['quote'], availabilityQuote=clause,
                 assetQuote='预训练模型' if '预训练模型' in clause else clause)
    assert validate_asset_availability(claim, audit, evidence) == ['AA_NO_EXPLICIT_RELEASE']


@pytest.mark.parametrize('change', [
    {'evidenceId': 'foreign'}, {'quote': 'An invented release passage'},
    {'availabilityQuote': 'Checkpoints are available'}, {'assetQuote': 'another checkpoint'},
    {'locator': 'https://example.org/invented'}, {'locator': 'https://example.org/model'},
    {'locator': 'file:///models'},
    {'locator': 'http://example.org/models'}, {'locator': ''},
])
def test_audit_cannot_invent_or_borrow_a_release_binding(change):
    claim, audit, evidence = inputs()
    audit.update(change)
    assert validate_asset_availability(claim, audit, evidence)


@pytest.mark.parametrize('change', [{'accessLevel': 'abstract'}, {'verification': {'literal': 'unchecked'}}])
def test_abstract_or_unverified_text_cannot_ground_a_checkpoint(change):
    claim, audit, evidence = inputs()
    evidence[0].update(change)
    assert validate_asset_availability(claim, audit, evidence) == ['AA_UNVERIFIED_FULLTEXT']


def test_own_fulltext_permission_and_unique_identity_are_required():
    claim, audit, evidence = inputs()
    claim['evidenceRefs'] = []
    assert validate_asset_availability(claim, audit, evidence) == ['AA_UNOWNED_EVIDENCE']
    claim['evidenceRefs'] = ['e']
    assert validate_asset_availability(claim, audit, evidence * 2) == ['AA_UNOWNED_EVIDENCE']


def test_model_pass_and_self_supplied_audit_cannot_override_missing_proof():
    claim, audit, evidence = inputs()
    claim['assetAvailability'] = audit  # Generated content is not a verifier verdict.
    claims = [claim, dependent('controls'), dependent('steps'), dependent('metrics')]
    result = verify_claims(claims, evidence, passed)
    assert [c['claimId'] for c in result['accepted']] == ['metrics']
    checks = {c['claimId']: c for c in result['rejected']}
    assert checks['budget']['reason'] == 'unverified_baseline_asset'
    assert checks['controls']['reason'] == checks['steps']['reason'] == 'baseline_asset_dependency'
    assert checks['budget']['assetPrerequisite'] is True


def test_failed_semantic_asset_target_also_invalidates_dependent_protocols():
    claim, audit, evidence = inputs()
    def semantic(claims, evidence):
        return [{**row, **({'status': 'failed', 'reason': 'Wrong scene/version.'}
                          if row['claimId'] == 'budget' else {})} for row in passed(claims, evidence)]
    result = verify_claims([claim, dependent('controls'), dependent('steps')], evidence, semantic)
    assert not result['accepted']
    assert len(result['rejected']) == 3


def test_finite_proposed_training_needs_no_released_asset_or_paper_training_settings():
    claim, _, _ = inputs()
    claim['executionSpec']['baseline'] = {
        'mode': 'train', 'unit': 'optimizer_steps', 'maxBudget': 12000, 'stoppingRule': 'Stop at 12000 steps.'}
    claim['evidenceRefs'] = []
    result = verify_claims([claim, dependent('controls'), dependent('steps')], [], passed)
    assert len(result['accepted']) == 3
    assert 'assetAvailability' not in result['accepted'][0]


def test_repairing_only_dependents_cannot_bypass_failed_budget():
    claim, _, evidence = inputs()
    initial = verify_claims([claim, dependent('steps')], evidence, passed)
    revised = {'accepted': [{**dependent('steps'), 'verification': 'proposal'}], 'rejected': []}
    checked = enforce_asset_prerequisites(merge_verified_revisions(initial, revised), evidence)
    assert not checked['accepted']


def test_repaired_training_baseline_removes_failed_asset_prerequisite():
    claim, _, evidence = inputs()
    initial = verify_claims([claim, dependent('steps')], evidence, passed)
    claim['executionSpec']['baseline'] = {
        'mode': 'train', 'unit': 'epochs', 'maxBudget': 20, 'stoppingRule': 'Stop at 20 epochs.'}
    revised = verify_claims([claim, dependent('steps')], evidence, passed)
    checked = enforce_asset_prerequisites(merge_verified_revisions(initial, revised), evidence)
    assert len(checked['accepted']) == 2
    assert not checked['rejected']


def test_verifier_evidence_alias_is_restored_for_asset_audit():
    claim, audit, evidence = inputs()
    def invoke(**kwargs):
        assert 'assetAvailability' in kwargs['prompt']
        assert 'authors trained a model does NOT establish public weights' in kwargs['prompt']
        wire = {**audit, 'evidenceId': 'E1'}
        verdict = {'claimId': 'budget', 'status': 'passed', 'assetAvailability': wire,
                   'designAudit': {'per_group_steps': {'fields': [{
                       'claimId': 'budget', 'path': ['executionSpec', 'recovery', 'groups'],
                       'value': claim['executionSpec']['recovery']['groups']}]}}}
        return {'content': json.dumps([verdict])}
    result = verify_claims([claim], evidence, BudgetedSemanticChecker(invoke, 'r'))
    assert result['accepted'][0]['assetAvailability']['evidenceId'] == 'e'


def test_resumed_publication_invalidates_coverage_without_source_bound_proof():
    claim, _, evidence = inputs()
    claims = [{**c, 'verification': 'proposal'} for c in [claim, dependent('controls'), dependent('steps')]]
    record = {'state': {'outputKind': 'experiment_design', 'evidence': evidence,
        'verifiedReport': {'verifiedClaims': claims, 'rejectedClaims': [],
                           'answerCoverage': {'status': 'checked', 'gaps': []}}}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r'})
    assert result['outcome'] == 'inconclusive'
    assert not publish.call_args.kwargs['payload']['claims']
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_design_contract'
