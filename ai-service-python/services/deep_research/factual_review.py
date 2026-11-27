"""Bounded initial factual review; never weakens the independent audit."""
from datetime import datetime, UTC

OPTION='_bounded_factual_review'
NAMED_TABLE_OPTION = '_named_table_factual_review'
REPAIR_OUTPUT_OPTION='_bounded_factual_repair_output'
DIRECT_REVIEW_OPTION='_direct_comparison_review'


def compact_comparison_prompt(targets):
    """The complete current comparison audit, with one source-path rule."""
    import json
    return '\nComparative targets and exact scopes: ' + json.dumps(targets, separators=(',', ':')) + '''
A supported comparative target requires comparisonAudit:
{"scope":"cross_study|within_study","alignment":"established|not_established|different",
 "supportsClaim":true,"premises":[{"evidenceId":"own E ID","path":["quote"]}],
 "conditionDifferences":[{"dimension":"actual evaluation condition",
  "left":{"evidenceId":"own E ID","path":["quote"],"value":"literal setting"},
  "right":{"evidenceId":"own E ID","path":["quote"],"value":"literal setting"}}]}.
Copy the exact scope enum. Bind each required source/version for cross_study. A name,
table cell or shared hardware label alone does not establish alignment or a causal effect.
Use different only for distinct literal values of the same relevant condition, bound
on both sides. Otherwise return conditionDifferences=[]. Unknown remains not_established.
Distinguish arithmetic, bounded system comparisons and controlled method effects.
A within-table observation can be bounded to that evaluation. Preserve original versus
re-trained baseline, relevant variants, datasets and direction. Do not rank across
unknown settings or claim comparison is inherently impossible. A why-question or
speculative confounder supplies no premise. A judgement needs its actual conditions
and limits; a cell inventory is not a judgement. If the actual conclusion or reason
lacks support, set scopeAudit.supported=false.
'''


COMPACT_SCOPE_PROMPT = '''
Every factual target requires scopeAudit:
{"claimStrength":"bounded|exclusive|universal","evidenceStrength":"bounded|exclusive|universal",
 "supported":true,"statementPath":["text"],"premises":[{"evidenceId":"own E ID","path":["quote"]}]}.
Review the whole text AND conditions, including ownership, table purpose and every clause.
Only applies/works at X asserts necessity; these citations only support X limits knowledge.
Finite observations or failures do not establish exclusivity or universality. The cited
premises must establish the actual strength and scope of the assertion. Do not turn a
profiling/ablation result into a main-table or original baseline result, or weaken text.
Use supported=false for any unsupported clause. The server independently checks all gates.
Bind scopeAudit/comparisonAudit to exact visible own source fields using evidenceId and
path only: ["quote"], ["sourceContext"] for string context, or ["sourceContext","before"]
/ ["sourceContext","after"] when supplied. Condition sides also need the literal value
present in that field. No retyped, omitted or foreign text. Paths are not scientific proof.
'''


def cell_review_enabled(record):
    """Review independent comparison points, regardless of total answer length."""
    from services.deep_research.comparison_generation import enabled as cells_enabled
    return (type(record.get('factualReviewContractVersion')) is int
            and record['factualReviewContractVersion'] == 4 and cells_enabled(record))


def named_table_review_enabled(record):
    version = record.get('namedTableBoundedReviewVersion')
    if (type(version) is not int or version != 1
            or (record.get('state') or {}).get('outputKind') != 'claim_verification'):
        return False
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.named_table_scope import requested_number
    from services.deep_research.request_context import effective_question

    question = effective_question(record)
    limit = requested_character_limit(question)
    return type(limit) is int and 0 < limit <= 700 and requested_number(question) is not None


def enabled(record):
    if cell_review_enabled(record) or named_table_review_enabled(record):
        return True
    if type(record.get('factualReviewContractVersion')) is not int or record['factualReviewContractVersion'] not in (1,2,3):
        return False
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.request_context import effective_question
    limit=requested_character_limit(effective_question(record))
    return type(limit) is int and 0<limit<=700 and record.get('state',{}).get('outputKind') in {
        'claim_verification','paper_comparison','direction_survey'}


def eligible(claims, *, max_targets=3):
    return bool(claims) and len(claims)<=max_targets and all(c.get('kind') in {'reported','inference'}
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
