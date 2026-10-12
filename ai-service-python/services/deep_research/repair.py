"""One bounded revision of rejected claims, without widening evidence or identity."""
from __future__ import annotations

import json
from copy import deepcopy

from services.deep_research.answer_constraints import answer_character_count, requested_character_limit, normalize_conditions, resolve_evidence_aliases
from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.selection import surrounding_context


def repair_rejected(report, verification, evidence, question, invoke, parse):
    rejected = {row['claimId']: row for row in verification.get('rejected', [])}
    originals = {row['claimId']: row for row in report.get('claims', []) if row.get('claimId') in rejected}
    if not originals:
        return []
    refs = {ref for row in originals.values() for ref in row.get('evidenceRefs', [])}
    selected = [e for e in evidence if e['evidenceId'] in refs]
    aliases = {f'E{i + 1}': e['evidenceId'] for i, e in enumerate(selected)}
    short_ids = {full: short for short, full in aliases.items()}
    input_claims = resolve_evidence_aliases({'claims': deepcopy(list(originals.values()))}, short_ids)['claims']
    prompt = f'''Revise only the rejected claims below. Narrow unsupported wording or omit the claim.
Question: {question}
Rejected claims and checks:
{json.dumps([{'claim': row, 'check': rejected[row['claimId']]} for row in input_claims], ensure_ascii=False)}
Exact available evidence:
{json.dumps([{'evidenceId': short_ids[e['evidenceId']], 'quote': e.get('quote', ''), 'sourceContext': surrounding_context(e), 'location': e.get('location', {}), 'accessLevel': e.get('accessLevel'), 'conditions': e.get('conditions', {}), 'tableData': e.get('tableData')} for e in selected], ensure_ascii=False)}
Return a COMPACT JSON array of revised claims, or [] when no supported revision is possible.
Keep claimId and kind. Use only a subset of that claim's original evidenceRefs; never turn a fact
into a proposal to evade checking. Preserve conditions needed for the narrower assertion.
Use the supplied short evidence IDs (E1, E2, ...) in both evidenceRefs and tableBindings.
Reported table numbers require tableBindings from tableData, using exactly these JSON keys:
{{"evidenceId":"E1","rowNumber":1,"groupIndex":0,"metric":"FPS","value":"200"}}
This is schema only, not evidence. Copy actual rowNumber, zero-based groupIndex, metric and value.
The key is "value", never "exactStringValue". Name dataset, method and metric beside each number.
When no verified cell is available, omit the numeric example rather than guessing a mapping.
An abstract supports only explicitly abstract-level wording (detailLevel="abstract").
Do not add new claims, searches, numbers or results. Fix invalid proposed formulas and label all
unexecuted proposals/hypotheses clearly. Keep the answer concise and within the user's length limit.'''
    try:
        response = invoke(prompt)
    except BudgetExhaustedError:
        return []
    finish = getattr(response, 'finish_reason', None) if not isinstance(response, dict) else response.get('finishReason', response.get('finish_reason'))
    if finish == 'length':
        return []
    content = response.content if hasattr(response, 'content') else response.get('content', '')
    revised = parse(content)
    if not isinstance(revised, list):
        return []
    revised = resolve_evidence_aliases({'claims': revised}, aliases)['claims']
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
