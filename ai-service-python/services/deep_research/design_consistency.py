"""Apply versioned cross-claim gates without promoting unchecked statements."""
from services.deep_research.budget_contract import enforce_budget_consistency
from services.deep_research.hypothesis_contract import enforce_hypothesis_consistency
from services.deep_research.asset_availability import enforce_asset_prerequisites
from services.deep_research.experiment_protocol import enforce_protocol_consistency


def enforce_design_consistency(verification, evidence=(), protocol_required=False):
    return enforce_hypothesis_consistency(enforce_budget_consistency(
        enforce_asset_prerequisites(enforce_protocol_consistency(verification,protocol_required), evidence)))
