"""Bounded initial factual review; never weakens the independent audit."""
from datetime import datetime, UTC

OPTION='_bounded_factual_review'


def enabled(record):
    if type(record.get('factualReviewContractVersion')) is not int or record['factualReviewContractVersion'] not in (1,2):
        return False
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.request_context import effective_question
    limit=requested_character_limit(effective_question(record))
    return type(limit) is int and 0<limit<=700 and record.get('state',{}).get('outputKind') in {
        'claim_verification','paper_comparison','direction_survey'}


def eligible(claims):
    return bool(claims) and len(claims)<=3 and all(c.get('kind') in {'reported','inference'}
        and not c.get('designRole') and not c.get('executionSpec')
        and len(c.get('text',''))<=1200 for c in claims)


def admission(record,history,args_digest,*,now=None):
    """Reuse matching history, including unknowns; admit new sends conservatively.

    Matching unknowns are NOT authorized to resend: the ordinary ledger still
    raises its unresolved-unknown protection. No reservation is made on refusal.
    Observed durations are advisory estimates, not guaranteed provider latency.
    """
    if not enabled(record):
        return {'allowed':True}
    matching=[c for c in history if c.get('node')=='verify' and c.get('tool')=='llm_invoke'
              and c.get('argsDigest',c.get('args_digest'))==args_digest]
    if matching:
        return {'allowed':True,'existingRequest':True}
    now=now or datetime.now(UTC)
    budget=record.get('budget',{})
    elapsed=float(budget.get('elapsedSeconds') or 0)
    started=record.get('startedAt')
    if started:
        elapsed=max(elapsed,(now-datetime.fromisoformat(started.replace('Z','+00:00'))).total_seconds())
    durations=[]
    for call in history:
        if (call.get('node')!='verify' or call.get('tool')!='llm_invoke'
                or call.get('status')!='succeeded' or call.get('settled')!=1):
            continue
        try:
            begin=datetime.fromisoformat(call.get('reservedAt',call.get('reserved_at','')).replace('Z','+00:00'))
            end=datetime.fromisoformat(call.get('completedAt',call.get('completed_at','')).replace('Z','+00:00'))
        except (KeyError,TypeError,ValueError):
            continue
        if end>begin:
            durations.append((end-begin).total_seconds())
    review_seconds=max(45.0,max(durations,default=0)*1.25+5)
    required=review_seconds+30.0  # Leave time for final coverage/publication.
    remaining=max(0.0,float(budget.get('maxWallClockSeconds') or 0)-max(0.0,elapsed))
    return {'allowed':remaining>=required,'remainingSeconds':round(remaining,3),
        'requiredSeconds':round(required,3),'observedSettledReviews':len(durations)}
