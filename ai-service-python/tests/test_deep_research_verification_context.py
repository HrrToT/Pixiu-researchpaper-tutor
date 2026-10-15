"""Operational context must not lose explicit dependencies or science review."""
import json
from copy import deepcopy

import pytest

from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification_context import configuration_context


def claim(key, role, text='', **extra):
    return {'claimId': key, 'kind': 'proposal', 'designRole': role,
            'text': text or key, 'evidenceRefs': [], **extra}


def targets(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Claims:\n', 1)[1].lstrip())[0]


def context(prompt):
    return json.JSONDecoder().raw_decode(prompt.split(
        'Other proposed statements, for consistency only (not evidence and not verdict targets):\n', 1)[1])[0]


def test_operational_context_keeps_transitive_id_references_and_original_order():
    target = claim('c_budget', 'budget', executionSpec={'analysisClaimId': 'c_analysis'})
    rows = [claim('c_limits', 'limits', 'Depend on c_hypothesis.'),
            claim('c_unused', 'limits', 'Unreferenced prose.'),
            claim('c_controls', 'controls'),
            claim('c_hypothesis', 'hypothesis'),
            claim('c_analysis', 'analysis', 'Use c_limits.'),
            claim('c_data', 'data')]
    before = deepcopy([target, rows])
    selected = configuration_context([target], rows)
    assert [c['claimId'] for c in selected] == ['c_limits', 'c_controls', 'c_hypothesis', 'c_analysis', 'c_data']
    assert [target, rows] == before


@pytest.mark.parametrize('reference', ['prefix_c_analysis', 'c_analysis_more', 'c_analysis-extra'])
def test_partial_id_substrings_do_not_promote_unrelated_prose(reference):
    selected = configuration_context([claim('c_groups', 'groups', reference)],
                                     [claim('c_analysis', 'analysis'), claim('c_data', 'data')])
    assert [c['claimId'] for c in selected] == ['c_data']


@pytest.mark.parametrize('repair', [False, True])
def test_config_and_science_review_keep_their_own_targets_permissions_and_definitions(repair):
    rows = [claim('c_groups', 'groups', 'Operational choice.'),
            claim('c_analysis', 'analysis', 'Interpret the operational choice.'),
            claim('c_controls', 'controls', 'Another operational choice.')]
    saved = deepcopy(rows)
    sent = []

    def invoke(**request):
        sent.append(request)
        prompt = request['prompt']
        active, shared = targets(prompt), context(prompt)
        supplied = {c['claimId']: c['text'] for c in [*active, *shared]}
        if request['node'].endswith('design_config'):
            assert supplied == {c['claimId']: c['text'] for c in rows if c['designRole'] != 'analysis'}
        else:
            assert supplied == {c['claimId']: c['text'] for c in rows}
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'failed'} for c in active])}

    checker = BudgetedSemanticChecker(invoke, 'run')
    checked = checker.check_revisions(rows, [], []) if repair else checker(rows, [])
    assert [v['claimId'] for v in checked] == [c['claimId'] for c in rows]
    assert len(sent) == 2 and all(r['use_reserve'] for r in sent)
    assert sent[0]['node'] == ('verify_repair_design_config' if repair else 'verify_design_config')
    assert rows == saved


def test_scientific_context_is_not_clipped_even_when_operational_check_fits():
    rows = [claim('c_groups', 'groups', 'Small configuration.'),
            claim('c_analysis', 'analysis', 'A' * 30000)]
    sent = []

    def invoke(**request):
        sent.append(request)
        return {'content': '[{"claimId":"c_groups","status":"failed"}]'}

    with pytest.raises(BudgetExhaustedError) as error:
        BudgetedSemanticChecker(invoke, 'run')(rows, [])
    assert error.value.details['kind'] == 'verificationPromptBytes'
    assert [r['node'] for r in sent] == ['verify_design_config']


def test_explicit_large_scientific_dependency_cannot_be_dropped_to_fit_configuration():
    rows = [claim('c_groups', 'groups', 'Follow c_analysis.'),
            claim('c_analysis', 'analysis', 'A' * 30000)]

    def invoke(**request):
        pytest.fail('Required dependency exceeds input capacity; must stop before dispatch.')

    with pytest.raises(BudgetExhaustedError):
        BudgetedSemanticChecker(invoke, 'run')(rows, [])


def test_limits_keep_factual_evidence_and_full_configuration_without_unused_audit_schema():
    target = claim('c_limits', 'limits', 'A limitation.', designContractVersion=2, evidenceRefs=['own'])
    shared = claim('c_controls', 'controls', 'A' * 9000)
    evidence = [{'evidenceId': 'own', 'quote': 'B' * 5000},
                {'evidenceId': 'unrelated', 'quote': 'UNRELATED_SOURCE'}]
    sent = []

    def invoke(**request):
        prompt = request['prompt']
        sent.append(prompt)
        assert len(prompt.encode()) <= 24000
        assert shared['text'] in prompt and evidence[0]['quote'] in prompt
        assert 'UNRELATED_SOURCE' not in prompt
        assert 'Allowed slot roots' not in prompt
        assert 'Near equality/non-significance proves neither' in prompt
        return {'content': '[{"claimId":"c_limits","status":"failed"}]'}

    result = BudgetedSemanticChecker(invoke, 'run').check_revisions([target], evidence, [shared])
    assert len(sent) == 1 and result[0]['status'] == 'failed'
