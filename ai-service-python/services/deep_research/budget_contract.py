"""Versioned budget opt-in and cross-claim checks; never rewrite legacy reports."""
from copy import deepcopy


def stamp_budget_contract(report, enabled=True):
    """New synthesis opts in; model output cannot remove the required marker."""
    result = deepcopy(report)
    result.pop('budgetContractVersion', None)
    if enabled:
        result['budgetContractVersion'] = 1
    for claim in result.get('claims', []):
        if isinstance(claim, dict):
            claim.pop('budgetContractVersion', None)
            if enabled and claim.get('designRole') == 'budget':
                claim['budgetContractVersion'] = 1
    return result


def enforce_budget_consistency(verification):
    """Compare only accepted definitions, including after merging revisions.

    Reject the budget when its group mapping cannot be established. Existing
    facts and legacy unmarked budgets are untouched; this is not a semantic pass.
    """
    from services.deep_research.budget_spec import budget_group_errors

    result = deepcopy(verification)
    accepted = result.get('accepted', [])
    budgets = [c for c in accepted if c.get('designRole') == 'budget'
               and type(c.get('budgetContractVersion')) is int and c['budgetContractVersion'] == 1]
    if not budgets:
        return result
    groups = [c for c in accepted if c.get('designRole') == 'groups'
              and c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
    rejected_ids = set()
    for budget in budgets:
        if len(budgets) != 1:
            errors = ['ambiguous_budget_definitions']
        elif len(groups) != 1:
            errors = ['missing_or_ambiguous_verified_groups']
        else:
            errors = budget_group_errors(budget.get('executionSpec'), groups[0].get('executionSpec'))
        if errors:
            rejected_ids.add(budget['claimId'])
            result.setdefault('rejected', []).append({'claimId': budget['claimId'],
                'reason': 'inconsistent_budget_groups', 'detail': ', '.join(errors)})
    result['accepted'] = [c for c in accepted if c.get('claimId') not in rejected_ids]
    return result
