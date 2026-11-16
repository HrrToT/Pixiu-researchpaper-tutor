"""Call capacity for a complete candidate before verification starts.

This is a lower bound, not a semantic pass or a prediction of provider latency.
No point or frozen user requirement is removed to make the candidate fit.
"""


def after_synthesis(record):
    state = record.get('state', {})
    if (record.get('stage') != 'synthesize' or state.get('outputKind') != 'paper_comparison'
            or type(record.get('claimIsolationContractVersion')) is not int
            or record['claimIsolationContractVersion'] != 1):
        return {'version': 1, 'status': 'unsupported_policy'}
    budget = record.get('budget', {})
    keys = ('maxModelCalls', 'modelCalls', 'reservedModelCalls')
    if any(type(budget.get(key, 0)) is not int or budget.get(key, 0) < 0 for key in keys):
        raise ValueError('Invalid comparison call budget')
    maximum, ordinary, reserved = (budget.get(key, 0) for key in keys)
    if ordinary + reserved > maximum:
        raise ValueError('Comparison call budget already exceeded')
    claims = state.get('reportBody', {}).get('claims', [])
    identities = [claim['claimId'] for claim in claims]
    if len(set(identities)) != len(identities):
        raise ValueError('Ambiguous comparison candidate identity')
    from services.deep_research.general_advice import enabled, eligible
    facts = [c for c in claims if c.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}]
    proposals = [c for c in claims if c not in facts]
    advice = [c for c in proposals if enabled(record) and eligible(c)]
    science = [c for c in proposals if c not in advice]
    # Each isolated factual point needs its own semantic review. Scope operators,
    # capacity splits, repairs or invalid responses can require additional calls.
    review = len(facts) + bool(advice) + bool(science)
    audit = int(bool(claims))
    remaining = maximum - ordinary - reserved
    return {'version': 1, 'status': 'estimated', 'draftPoints': len(claims),
            'remainingModelCalls': remaining, 'minimumReviewCalls': review,
            'minimumWholeAnswerAuditCalls': audit,
            'minimumAdditionalCalls': review + audit,
            'fitsCallLowerBound': remaining >= review + audit,
            'callsBeyondLowerBound': max(0, remaining - review - audit),
            'tokensAndTimeFitEstablished': False, 'scientificApproval': False}
