"""One bounded revision of rejected claims, without widening evidence or identity."""
from __future__ import annotations

import json

from services.deep_research.answer_constraints import answer_character_count, requested_character_limit, normalize_conditions
from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.selection import surrounding_context


def repair_rejected(report, verification, evidence, question, invoke, parse):
    rejected = {row['claimId']: row for row in verification.get('rejected', [])}
    originals = {row['claimId']: row for row in report.get('claims', []) if row.get('claimId') in rejected}
    if not originals:
        return []
    refs = {ref for row in originals.values() for ref in row.get('evidenceRefs', [])}
    prompt = f'''Revise only the rejected claims below. Narrow unsupported wording or omit the claim.
Question: {question}
Rejected claims and checks:
{json.dumps([{'claim': row, 'check': rejected[key]} for key, row in originals.items()], ensure_ascii=False)}
Exact available evidence:
{json.dumps([{'evidenceId': e['evidenceId'], 'quote': e.get('quote', ''), 'sourceContext': surrounding_context(e), 'location': e.get('location', {}), 'accessLevel': e.get('accessLevel'), 'conditions': e.get('conditions', {})} for e in evidence if e['evidenceId'] in refs], ensure_ascii=False)}
Return a JSON array of revised claims, or [] when no supported revision is possible.
Keep claimId and kind. Use only a subset of that claim's original evidenceRefs; never turn a fact
into a proposal to evade checking. Preserve conditions needed for the narrower assertion.
An abstract supports only explicitly abstract-level wording (detailLevel="abstract").
Do not add new claims, searches, numbers or results. Fix invalid proposed formulas and label all
unexecuted proposals/hypotheses clearly. Keep the answer concise and within the user's length limit.'''
    try:
        response = invoke(prompt)
    except BudgetExhaustedError:
        return []
    content = response.content if hasattr(response, 'content') else response.get('content', '')
    revised = parse(content)
    if not isinstance(revised, list):
        return []
    valid, seen = [], set()
    for row in revised:
        if not isinstance(row, dict):
            continue
        key = row.get('claimId')
        original = originals.get(key)
        if not original or key in seen or row.get('kind') != original.get('kind'):
            continue
        seen.add(key)
        new_refs = row.get('evidenceRefs', [])
        if not isinstance(new_refs, list) or any(ref not in original.get('evidenceRefs', []) for ref in new_refs):
            continue
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            continue
        valid.append(normalize_conditions({'claims': [dict(row)]})['claims'][0])
    candidate = {'claims': [*verification.get('accepted', []), *valid]}
    limit = requested_character_limit(question)
    return [] if limit and answer_character_count(candidate) > limit else valid
