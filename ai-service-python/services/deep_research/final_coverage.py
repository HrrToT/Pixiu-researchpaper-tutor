"""A bounded final-answer audit, distinct from retrieval and factual verification."""
import json

from services.deep_research.contracts import BudgetExhaustedError


def audit_final_answer(run_id, question, plan, claims, evidence, invoke, parse):
    from services.deep_research.answer_coverage import answer_coverage_gaps
    from services.deep_research.selection import balanced_sample, surrounding_context

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
    invalid_aspects = []
    if claims and plan and invoke:
        selected = balanced_sample(evidence,
            lambda e: (e.get('sourceWorkId'), tuple(e.get('obligationIds', []))), 20)
        from uuid import uuid4
        from services.deep_research.prompt_budget import fit_evidence_prompt
        evidence_marker = uuid4().hex
        rows = [{
            'evidenceId': e['evidenceId'], 'quote': e.get('quote', ''),
            'sourceContext': surrounding_context(e), 'source': e.get('sourceWorkId'),
            'conditions': e.get('conditions', {}),
        } for e in selected]
        prompt = f'''Audit whether the FINAL ACCEPTED ANSWER fully answers the user's question.
Question: {question}
Answer obligations (including the original question): {json.dumps([o for p in audit_plan for o in p.get('obligations', [])], ensure_ascii=False)}
Accepted final claims: {json.dumps(claims, ensure_ascii=False, sort_keys=True)}
Available evidence for detecting omitted conditions: {evidence_marker}

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
Before deciding covered, enumerate the minimal essential aspects separately:
entities and their relationships, conditioning inputs, activation/applicability
rules, requested comparisons and guarantee boundaries, as applicable. Identify
these from the question AND the supplied source passages, not from what the
answer happened to mention. Do not merge distinct conditioning inputs into one
vague aspect. A missing aspect remains missing even if every stated sentence is true.
For each aspect quote its basis (request or source) and the exact answer text
that covers it. A source requirement must have an evidenceId and exact excerpt.
When checking factual claims with available evidence, include source-grounded
essential aspects; quoting only the broad user question is insufficient.
Check the subject of contrasts and pronouns against preceding sentences: a
baseline's limitation cannot be assigned to the proposed method.
Return only a JSON array, exactly one entry for each supplied obligation:
[{{"obligationId":"ID","status":"covered|partial|missing",
   "bindings":[{{"claimId":"an accepted ID","excerpt":"exact substring of that claim's text or serialized conditions, at least 8 characters"}}],
   "aspects":[{{"aspectId":"unique within this obligation","requirement":"one necessary aspect",
     "basis":{{"kind":"request|source","evidenceId":"required for source","excerpt":"exact basis text"}},
     "status":"covered|partial|missing",
     "bindings":[{{"claimId":"accepted ID","excerpt":"exact answer substring, at least 8 characters"}}]}}]}}]
Covered requires every essential aspect to be covered with its own binding.
Do not fabricate a binding for a missing aspect; use an empty bindings array.
Only mark covered if ALL requested aspects of that obligation are answered in the
accepted claims. Bindings must quote the final answer, never the source passages.'''
        template = prompt
        prompt, rows = fit_evidence_prompt(rows,
            lambda selected_rows: template.replace(evidence_marker, json.dumps(selected_rows, ensure_ascii=False), 1))
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
            if isinstance(verdicts, list):
                # Explicitly reported missing subrequirements override an
                # inconsistent overall "covered", and remain repairable gaps.
                verdicts = [{**v, 'status': 'partial'} if isinstance(v, dict)
                    and v.get('status') == 'covered' and isinstance(v.get('aspects'), list)
                    and any(isinstance(a, dict) and a.get('status') in {'partial', 'missing'}
                            for a in v['aspects']) else v for v in verdicts]
                from services.deep_research.coverage_aspects import invalid_coverage_aspects
                invalid_aspects = invalid_coverage_aspects(verdicts, claims, rows,
                    [question, *[o.get('question', '') for p in audit_plan for o in p.get('obligations', [])]],
                    request_only_obligations=[identity] if identity else [])
                if invalid_aspects:
                    verdicts = [{**v, 'status': 'partial'} if isinstance(v, dict)
                        and v.get('obligationId') in invalid_aspects else v for v in verdicts]
                    status = 'invalid_response'
        except BudgetExhaustedError:
            # Publish only supported text with an explicit coverage gap. Never
            # promote budget exhaustion to a complete answer or add a retry.
            status = 'budget_exhausted'
    gaps = answer_coverage_gaps(audit_plan, claims, verdicts)
    for gap in gaps:
        matching = [v for v in verdicts if isinstance(v, dict)
                    and v.get('obligationId') == gap.get('obligationId')] if isinstance(verdicts, list) else []
        if len(matching) == 1 and isinstance(matching[0].get('aspects'), list):
            gap['missingAspects'] = list(dict.fromkeys(a['requirement'].strip()
                for a in matching[0]['aspects'] if isinstance(a, dict)
                and a.get('status') in {'partial', 'missing'}
                and isinstance(a.get('requirement'), str) and a['requirement'].strip()))
            gap['aspectEvidenceRefs'] = list(dict.fromkeys(a['basis']['evidenceId']
                for a in matching[0]['aspects'] if isinstance(a, dict)
                and a.get('status') in {'partial', 'missing'}
                and isinstance(a.get('basis'), dict) and a['basis'].get('kind') == 'source'
                and isinstance(a['basis'].get('evidenceId'), str)))
        if status in {'budget_exhausted', 'invalid_response'}:
            gap['missingEvidence'] = '回答完整性尚未核验'
            gap['auditStatus'] = status
        if identity and gap.get('obligationId') == identity:
            gap['wholeQuestion'] = True
    return {'status': status, 'verdicts': verdicts if isinstance(verdicts, list) else [],
            'gaps': gaps, 'invalidAspectObligations': invalid_aspects}


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
