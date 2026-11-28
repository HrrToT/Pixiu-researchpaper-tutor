from copy import deepcopy
import json

import pytest

from services.deep_research.design_audit import validate_design_audit
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_shared_experiment_repair import inputs


def analysis_and_verdict():
    report, _, _ = inputs()
    claim = next(c for c in report['claims'] if c['designRole'] == 'analysis')
    verdict = {'claimId': claim['claimId'], 'status': 'passed', 'designAudit': {
        slot: {'claimId': claim['claimId'], 'path': ['executionSpec', key],
            'value': deepcopy(claim['executionSpec'][key])}
        for slot, key in [('effects', 'effects'), ('uncertainty', 'uncertainty'), ('decision_rule', 'decision')]}}
    return claim, verdict


def test_exact_direct_fields_reuse_existing_checks_and_leave_original_verdict_untouched():
    claim, verdict = analysis_and_verdict(); before = deepcopy((claim, verdict))
    assert validate_design_audit(claim, verdict, []) == ['effects', 'uncertainty', 'decision_rule']
    assert validate_design_audit(claim, verdict, [], direct_fields=True) == []
    wrapped = deepcopy(verdict)
    wrapped['designAudit'] = {slot: {'fields': [entry]} for slot, entry in verdict['designAudit'].items()}
    assert validate_design_audit(claim, wrapped, []) == []
    assert (claim, verdict) == before


@pytest.mark.parametrize('change', ['value', 'path', 'role', 'unknown_id', 'extra_quote', 'extra_ref',
    'extra_fields', 'missing_value', 'missing_slot', 'boolean_index'])
def test_direct_binding_does_not_accept_wrong_values_paths_roles_or_mixed_forms(change):
    claim, verdict = analysis_and_verdict(); entry = verdict['designAudit']['effects']
    if change == 'value': entry['value'] = {'invented': 'effect'}
    elif change == 'path': entry['path'] = ['executionSpec', 'decision']; entry['value'] = claim['executionSpec']['decision']
    elif change == 'role': claim['designRole'] = 'limits'
    elif change == 'unknown_id': entry['claimId'] = 'unrelated'
    elif change == 'extra_quote': entry['quote'] = 'An extra interpretation'
    elif change == 'extra_ref': entry['ref'] = {'claimId': claim['claimId'], 'path': entry['path']}
    elif change == 'extra_fields': entry['fields'] = []
    elif change == 'missing_value': del entry['value']
    elif change == 'missing_slot': del verdict['designAudit']['effects']
    elif change == 'boolean_index': entry['path'] = ['executionSpec', 'effects', True]
    if change == 'role':
        # Binding an actual limits context into an analysis slot must fail.
        original, _ = analysis_and_verdict()
        entry['claimId'] = 'other'; claim['claimId'] = 'other'
        assert 'effects' in validate_design_audit(original, verdict, [claim], direct_fields=True)
    else:
        assert 'effects' in validate_design_audit(claim, verdict, [], direct_fields=True)


def test_single_baseline_binding_cannot_satisfy_recovery_budget_slot():
    report, _, _ = inputs(); budget = next(c for c in report['claims'] if c['designRole'] == 'budget')
    entry = {'claimId': budget['claimId'], 'path': ['executionSpec', 'baseline'], 'value': budget['executionSpec']['baseline']}
    verdict = {'designAudit': {'per_group_steps': entry}}
    assert validate_design_audit(budget, verdict, [], direct_fields=True) == ['per_group_steps']
    entry.update(path=['executionSpec', 'recovery'], value=budget['executionSpec']['recovery'])
    assert not validate_design_audit(budget, verdict, [], direct_fields=True)


@pytest.mark.parametrize('version,expected', [(False, 'failed'), (1, 'failed'), (2, 'passed')])
def test_semantic_checker_uses_exact_new_server_version_without_changing_failed_verdicts(version, expected):
    claim, verdict = analysis_and_verdict(); sent = []
    def invoke(**request):
        sent.append(request); return {'content': json.dumps([verdict])}
    checker = BudgetedSemanticChecker(invoke, 'offline', prospective_review=version)
    result = checker([claim], inputs()[2])
    assert result[0]['status'] == expected
    assert ('Typed audit contract 2' in sent[0]['prompt']) is (version == 2)
    verdict['status'] = 'failed'; verdict['reason'] = 'Unresolved measurement method.'
    assert checker([claim], inputs()[2])[0]['status'] == 'failed'


def test_empty_or_noncanonical_source_spec_does_not_become_valid_via_binding_format():
    claim, verdict = analysis_and_verdict()
    claim['executionSpec']['effects'] = {}
    verdict['designAudit']['effects']['value'] = {}
    assert validate_design_audit(claim, verdict, [], direct_fields=True)
