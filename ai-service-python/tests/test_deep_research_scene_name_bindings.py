"""Display labels may differ in case; source identity must remain exact."""
from copy import deepcopy
import json

import pytest

from services.deep_research.data_availability import validate_data_availability
from services.deep_research.execution_materialization import materialize_execution_claim
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims


def inputs():
    quote = 'The Synthetic benchmark includes the Hotdog scene.'
    claim = materialize_execution_claim({
        'claimId': 'data', 'kind': 'proposal', 'designRole': 'data', 'designContractVersion': 2,
        'text': 'Proposed descriptive comparison on the hotdog scene.', 'evidenceRefs': ['e'],
        'executionSpec': {'dataset': 'Synthetic benchmark',
            'scenes': {'mode': 'named', 'names': ['hotdog']},
            'split': {'mode': 'every_nth', 'order': 'filename', 'stride': 8, 'offset': 0},
            'seeds': [0], 'independentUnit': 'scene', 'replication': {'mode': 'fixed_checkpoint'}}})
    evidence = [{'evidenceId': 'e', 'quote': quote, 'verification': {'literal': 'passed'},
                 'accessLevel': 'fulltext', 'sourceWorkId': 'paper', 'sourceVersionId': 'v1'}]
    verdict = {'claimId': 'data', 'status': 'passed', 'dataAvailability': {
        'evidenceId': 'e', 'quote': quote, 'scopeQuote': 'Synthetic benchmark',
        'availableNames': ['Hotdog'],
        'nameBindings': [{'selectedName': 'hotdog', 'sourceLabel': 'Hotdog'}]},
        'designAudit': {slot: {'claimId': 'data', 'quote': claim['text']}
                        for slot in ('scenes', 'split', 'seeds', 'sampling_unit')}}
    return claim, verdict, evidence


def test_bound_case_variant_preserves_literal_quote_and_requested_selection():
    claim, verdict, evidence = inputs()
    before = deepcopy((claim, verdict, evidence))
    assert validate_data_availability(claim, verdict, evidence) == []
    assert (claim, verdict, evidence) == before


def test_no_silent_case_folding_without_explicit_binding():
    claim, verdict, evidence = inputs()
    del verdict['dataAvailability']['nameBindings']
    assert validate_data_availability(claim, verdict, evidence) == ['DA_NAME_NOT_AVAILABLE']


@pytest.mark.parametrize('binding', [
    {'selectedName': 'hotdog', 'sourceLabel': 'Chair'},
    {'selectedName': 'hotdog', 'sourceLabel': 'hotdog'},
    {'selectedName': 'other', 'sourceLabel': 'Other'},
    {'selectedName': '../hotdog', 'sourceLabel': '../Hotdog'},
    {'selectedName': 'arxiv:2312.12337v4', 'sourceLabel': 'ARXIV:2312.12337V4'},
    {'selectedName': 'hotdog.pdf', 'sourceLabel': 'Hotdog.PDF'},
    {'selectedName': 'ｈotdog', 'sourceLabel': 'Hotdog'},
    {'selectedName': 'hotdog', 'sourceLabel': 'Hot-dog'},
    {'selectedName': 'hotdog', 'sourceLabel': 'Hotdog', 'trusted': True},
    {'selectedName': None, 'sourceLabel': 'Hotdog'},
])
def test_unbound_or_fuzzy_identity_is_rejected(binding):
    claim, verdict, evidence = inputs()
    verdict['dataAvailability']['nameBindings'] = [binding]
    assert validate_data_availability(claim, verdict, evidence)


def test_source_label_still_has_to_exist_in_exact_quote():
    claim, verdict, evidence = inputs()
    verdict['dataAvailability']['availableNames'] = ['HOTDOG']
    verdict['dataAvailability']['nameBindings'][0]['sourceLabel'] = 'HOTDOG'
    assert validate_data_availability(claim, verdict, evidence) == ['DA_NAME_NOT_IN_QUOTE']


def test_case_variants_cannot_duplicate_one_physical_scene():
    claim, verdict, evidence = inputs()
    claim['executionSpec']['scenes']['names'].append('Hotdog')
    assert validate_data_availability(claim, verdict, evidence) == ['DA_NAME_BINDINGS_NOT_UNIQUE']


def test_audit_does_not_grant_other_evidence_permissions():
    claim, verdict, evidence = inputs()
    verdict['dataAvailability']['evidenceId'] = 'unowned'
    assert validate_data_availability(claim, verdict, evidence) == ['DA_EVIDENCE_NOT_FOUND']


def test_alias_restoration_and_semantic_check_keep_proposal_identity():
    claim, verdict, evidence = inputs()
    def invoke(**kwargs):
        assert 'nameBindings' in kwargs['prompt'] and 'ASCII letter-case' in kwargs['prompt']
        wire = deepcopy(verdict)
        wire['dataAvailability']['evidenceId'] = 'E1'
        return {'content': json.dumps([wire])}
    result = verify_claims([claim], evidence, BudgetedSemanticChecker(invoke, 'r'))
    assert result['accepted'][0]['verification'] == 'proposal'
    assert result['accepted'][0]['executionSpec']['scenes']['names'] == ['hotdog']
    assert not verify_claims([claim], evidence)['accepted']


def test_semantic_failure_still_rejects_structurally_bound_name():
    claim, verdict, evidence = inputs()
    verdict.update(status='failed', reason='The quote refers to a different benchmark subset.')
    result = verify_claims([claim], evidence, BudgetedSemanticChecker(
        lambda **kwargs: {'content': json.dumps([verdict])}, 'r'))
    assert not result['accepted']
