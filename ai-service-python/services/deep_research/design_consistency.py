"""Apply versioned cross-claim gates without promoting unchecked statements."""
from services.deep_research.budget_contract import enforce_budget_consistency
from services.deep_research.hypothesis_contract import enforce_hypothesis_consistency
from services.deep_research.asset_availability import enforce_asset_prerequisites
from services.deep_research.experiment_protocol import enforce_protocol_consistency


def enforce_design_consistency(verification, evidence=(), protocol_required=False, workflow_required=False):
    from services.deep_research.experiment_workflow import enforce_workflow_consistency
    current = verification
    # Canonical controls/workflow references are mutual. If either loses a
    # dependency in a later gate, repeat removal-only gates to remove orphans.
    # No gate may promote a rejected/unverified statement.
    coupled = (protocol_required == 2 or workflow_required == 4 or any(
        c.get('protocolContractVersion') == 2 or c.get('workflowContractVersion') == 4
        for c in verification.get('accepted', [])))
    for _ in range(len(verification.get('accepted', [])) + 1 if coupled else 1):
        checked = enforce_workflow_consistency(enforce_hypothesis_consistency(enforce_budget_consistency(
            enforce_asset_prerequisites(enforce_protocol_consistency(current,protocol_required), evidence))),
            required=workflow_required)
        if [c.get('claimId') for c in checked.get('accepted', [])] == [c.get('claimId') for c in current.get('accepted', [])]:
            return checked
        current = checked
    return current
