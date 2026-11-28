"""Display spelling must neither reject a conjunction nor erase table identity."""
from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.table_bindings import validate_table_bindings
from services.deep_research.verification import precheck_claims, verify_claims
from test_deep_research_table_bindings import fixture


def case(group='Tank and Temple Datasets', display='Tank&Temple'):
    ev, claim = fixture()
    ev['tableData']['groups'][0][0] = group
    claim['text'] = claim['text'].replace('Dataset A', display)
    return ev, claim


@pytest.mark.parametrize('group,display', [
    ('Tank and Temple Datasets', 'Tank&Temple'),
    ('Tank&Temple', 'Tank and Temple'),
    ('Tank and Temple / held-out', 'Tank&Temple 的 held-out'),
])
def test_only_new_policy_allows_conjunction_spelling(group, display):
    ev, claim = case(group, display)
    before = deepcopy((ev, claim))
    assert validate_table_bindings(claim, [ev]) == 'table_condition_not_displayed'
    assert validate_table_bindings(claim, [ev], dataset_joiners=True) is None
    for version in (0, 1, 2, True, '3'):
        assert precheck_claims([claim], [ev], table_references_version=version)['rejected']
    assert not precheck_claims([claim], [ev], table_references_version=3)['rejected']
    assert (ev, claim) == before


@pytest.mark.parametrize('group,display', [
    ('Tank and Temple / held-out', 'Tank&Temple'),
    ('Tank and Temple 2', 'Tank&Temple'),
    ('Tank and Temple', 'Tank&Temple-heldout'),
    ('Tank and Temple', 'Tank'),
    ('Tank and Temple', 'Tank or Temple'),
    ('Tank and Temple', 'Tank+Temple'),
    ('Tank and Temple', 'Tanks&Temples'),
    ('Tank and Temple', 'OtherTank&Temple'),
    ('Rockland', 'Rockl&'),
])
def test_splits_numbers_and_other_names_remain_required(group, display):
    ev, claim = case(group, display)
    assert validate_table_bindings(claim, [ev], dataset_joiners=True) == 'table_condition_not_displayed'


@pytest.mark.parametrize('mutation,reason', [
    (lambda c: c['tableBindings'][0].update(value='135'), 'table_cell_mismatch'),
    (lambda c: c['tableBindings'][0].update(evidenceId='other'), 'table_binding_outside_citation'),
    (lambda c: c.update(text=c['text'].replace('Ours*', 'Ours')), 'table_condition_not_displayed'),
    (lambda c: c['tableBindings'][0].update(groupIndex=1), 'table_cell_mismatch'),
])
def test_joiner_does_not_change_exact_cell_or_method_gate(mutation, reason):
    ev, claim = case()
    mutation(claim)
    assert validate_table_bindings(claim, [ev], dataset_joiners=True) == reason


def test_passing_display_still_requires_independent_semantic_check():
    ev, claim = case()
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'unresolved', 'reason': 'not established'}])
    result = verify_claims([claim], [ev], checker, table_references_version=3)
    checker.assert_called_once()
    assert not result['accepted']


def test_policy_is_strict_boolean():
    ev, claim = case()
    with pytest.raises(ValueError):
        validate_table_bindings(claim, [ev], dataset_joiners=1)


def test_whitespace_already_accepted_by_legacy_stays_accepted():
    ev, claim = case('Tank & Temple Datasets', 'Tank&Temple')
    assert validate_table_bindings(claim, [ev]) is None
    assert validate_table_bindings(claim, [ev], dataset_joiners=True) is None
