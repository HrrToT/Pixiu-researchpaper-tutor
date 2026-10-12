"""A bounded final-answer audit, distinct from retrieval and factual verification."""
import json

from services.deep_research.contracts import BudgetExhaustedError


def audit_final_answer(run_id, question, plan, claims, evidence, invoke, parse):
    from services.deep_research.answer_coverage import answer_coverage_gaps
    from services.deep_research.selection import balanced_sample, bounded_evidence_rows, surrounding_context

    # A plan can itself omit part of the request. Audit the original question as
    # well as each planned obligation, without changing the stored research plan.
    audit_plan = list(plan)
    identity = None
    if plan and question:
        known = {o['obligationId'] for p in plan for o in p.get('obligations', [])}
        identity = 'answer_scope'
        while identity in known:
            identity += '_'
        audit_plan.append({'obligations': [{'obligationId': identity, 'question': question}]})
    verdicts = []
    status = 'not_checked'
    if claims and plan and invoke:
        selected = balanced_sample(evidence,
            lambda e: (e.get('sourceWorkId'), tuple(e.get('obligationIds', []))), 20)
        rows = bounded_evidence_rows([{
            'evidenceId': e['evidenceId'], 'quote': e.get('quote', ''),
            'sourceContext': surrounding_context(e), 'source': e.get('sourceWorkId'),
            'conditions': e.get('conditions', {}),
        } for e in selected])
        prompt = f'''Audit whether the FINAL ACCEPTED ANSWER fully answers the user's question.
Question: {question}
Answer obligations (including the original question): {json.dumps([o for p in audit_plan for o in p.get('obligations', [])], ensure_ascii=False)}
Accepted final claims: {json.dumps(claims, ensure_ascii=False, sort_keys=True)}
Available evidence for detecting omitted conditions: {json.dumps(rows, ensure_ascii=False)}

Factual support has been checked separately. Do NOT mistake a true sentence, a relevant
retrieval, a claim's obligationIds, or the existence of a citation for a complete answer.
Judge the actual accepted text and its conditions. An accurate high-level summary is
partial if it omits parameters, activation rules, assumptions or comparisons needed to
answer this particular question. Preserve the requested brevity: do not demand every
paper detail, implementation detail, extra experiment or background the user did not ask for.
For a mechanism question, check the requested entities, their relationships, the relevant
conditioning inputs, and when the mechanism applies, using the supplied passages.
For a comparison, check every requested dimension and each paper's contribution, not
just one paper's results. A source-specific, clearly stated evidence limitation can
answer an uncertainty question; do not demand proof of a universal guarantee.
An unexecuted experiment may be complete as a proposal; do not demand measured results.
Do not rewrite the answer, add claims, change factual verdicts, or judge rejected claims.
Return only a JSON array, exactly one entry for each supplied obligation:
[{{"obligationId":"ID","status":"covered|partial|missing",
   "bindings":[{{"claimId":"an accepted ID","excerpt":"exact substring of that claim's text or serialized conditions, at least 8 characters"}}]}}]
Only mark covered if ALL requested aspects of that obligation are answered in the
accepted claims. Bindings must quote the final answer, never the source passages.'''
        try:
            result = invoke(run_id, 'verify_answer_coverage', prompt,
                            {'max_tokens': 3500, 'temperature': 0.0}, use_reserve=True)
            content = result.get('content', '') if isinstance(result, dict) else getattr(result, 'content', '')
            finish = result.get('finishReason', result.get('finish_reason')) if isinstance(result, dict) else getattr(result, 'finish_reason', None)
            try:
                verdicts = parse(content) if finish != 'length' else None
            except (ValueError, TypeError):
                verdicts = None
            status = 'checked' if isinstance(verdicts, list) else 'invalid_response'
        except BudgetExhaustedError:
            # Publish only supported text with an explicit coverage gap. Never
            # promote budget exhaustion to a complete answer or add a retry.
            status = 'budget_exhausted'
    gaps = answer_coverage_gaps(audit_plan, claims, verdicts)
    for gap in gaps:
        if identity and gap.get('obligationId') == identity:
            gap['wholeQuestion'] = True
    return {'status': status, 'verdicts': verdicts if isinstance(verdicts, list) else [], 'gaps': gaps}


def remaining_retrieval_gaps(gaps, audit, claims, evidence):
    """Close an earlier retrieval gap only with a checked answer for that source.

    A bounded inference about insufficient evidence may answer an obligation
    even when retrieval cannot find a universal guarantee. Another paper's
    conclusion, a proposal, or an unchecked audit never closes this gap.
    """
    if audit.get('status') != 'checked':
        return list(gaps)
    missing = {g.get('obligationId') for g in audit.get('gaps', [])}
    from services.deep_research.answer_coverage import answer_coverage_gaps
    check_plan = [{'obligations': [g for g in gaps if isinstance(g, dict) and g.get('obligationId')]}]
    missing.update(g.get('obligationId') for g in answer_coverage_gaps(check_plan, claims, audit.get('verdicts')))
    accepted = {c.get('claimId'): c for c in claims
                if c.get('verification') == 'semantic_passed' and c.get('kind') in {'reported', 'inference'}}
    origins = {e.get('evidenceId'): e.get('sourceWorkId') for e in evidence
               if e.get('verification', {}).get('literal') == 'passed'}
    covered = {}
    for verdict in audit.get('verdicts', []):
        oid = verdict.get('obligationId')
        if verdict.get('status') != 'covered' or oid in missing:
            continue
        works = set()
        for binding in verdict.get('bindings', []):
            claim = accepted.get(binding.get('claimId'), {})
            works.update(origins[ref] for ref in claim.get('evidenceRefs', []) if origins.get(ref))
        covered[oid] = works
    return [gap for gap in gaps if not isinstance(gap, dict)
            or gap.get('sourceWorkId') not in covered.get(gap.get('obligationId'), set())]
