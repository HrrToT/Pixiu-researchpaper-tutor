"""Apply versioned cross-claim gates without promoting unchecked statements."""
from services.deep_research.budget_contract import enforce_budget_consistency
from services.deep_research.hypothesis_contract import enforce_hypothesis_consistency


def enforce_design_consistency(verification):
    return enforce_hypothesis_consistency(enforce_budget_consistency(verification))
