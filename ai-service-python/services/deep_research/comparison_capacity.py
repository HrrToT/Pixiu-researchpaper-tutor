"""Call capacity for a complete candidate before verification starts.

This is a lower bound, not a semantic pass or a prediction of provider latency.
No point or frozen user requirement is removed to make the candidate fit.
"""


def before_synthesis(record, point_constraint=None):
    """Allocate isolated review slots before generation; never grant approval.

    Reserve generation, whole-answer audit and one repair request. This is only
    call allocation: scope checks, audit splits, tokens and time can cost more.
    Both ledger counters are spent calls, not pending reservations.
    """
    budget = record.get('budget', {})
    keys = ('maxModelCalls', 'modelCalls', 'reservedModelCalls')
    if any(type(budget.get(key)) is not int or budget[key] < 0 for key in keys):
        raise ValueError('Invalid comparison call budget')
    maximum, ordinary, reserved = (budget[key] for key in keys)
    remaining = maximum - ordinary - reserved
    if remaining < 0:
        raise ValueError('Comparison call budget already exceeded')
    overhead = 3
    capacity = min(24, max(0, remaining - overhead))
    if point_constraint is not None:
        if (not isinstance(point_constraint, dict)
                or type(point_constraint.get('count')) is not int
                or point_constraint['count'] < 1
                or point_constraint.get('mode') not in ('exact', 'max')):
            raise ValueError('Invalid comparison point constraint')
        required = point_constraint['count'] if point_constraint['mode'] == 'exact' else 1
        capacity = min(capacity, point_constraint['count'])
    else:
        required = 1
    if capacity < required:
        from services.deep_research.contracts import BudgetExhaustedError
        raise BudgetExhaustedError('comparisonDraftAllocationCalls', remaining, required + overhead)
    return {'version': 2, 'status': 'allocated_unverified',
            'maxDraftPoints': capacity, 'remainingModelCalls': remaining,
            'generationAuditAndRepairCalls': overhead,
            'tokensAndTimeFitEstablished': False, 'scientificApproval': False}


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
