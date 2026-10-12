"""One bounded revision within the acquired source versions, followed by verification."""
from __future__ import annotations

import json
from copy import deepcopy

from services.deep_research.answer_constraints import answer_character_count, requested_character_limit, normalize_conditions, resolve_evidence_aliases
from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.selection import surrounding_context, bounded_evidence_rows
from services.deep_research.repair_scope import repair_evidence_scope


def repair_rejected(report, verification, evidence, question, invoke, parse):
    rejected = {row['claimId']: row for row in verification.get('rejected', [])}
    originals = {row['claimId']: row for row in report.get('claims', []) if row.get('claimId') in rejected}
    if not originals:
        return []
    hinted = {ref for row in rejected.values() for ref in row.get('missingEvidenceRefs', [])
              if isinstance(ref, str)}
    evidence = sorted(evidence, key=lambda e: e.get('evidenceId') not in hinted)
    allowed = repair_evidence_scope(list(originals.values()), evidence)
    refs = {ref for values in allowed.values() for ref in values}
    selected = [e for e in evidence if e['evidenceId'] in refs]
    aliases = {f'E{i + 1}': e['evidenceId'] for i, e in enumerate(selected)}
    short_ids = {full: short for short, full in aliases.items()}
    original_refs = {ref for row in originals.values() for ref in row.get('evidenceRefs', [])}
    rows = bounded_evidence_rows([
        {'evidenceId': short_ids[e['evidenceId']], 'quote': e.get('quote', ''),
         'sourceContext': surrounding_context(e), 'location': e.get('location', {}),
         'accessLevel': e.get('accessLevel'), 'conditions': e.get('conditions', {}),
         'tableData': e.get('tableData')}
        for e in sorted(selected, key=lambda e: (e['evidenceId'] not in hinted,
                                                 e['evidenceId'] not in original_refs))
    ], max_bytes=20000)
    visible = {aliases[row['evidenceId']] for row in rows}
    allowed = {key: [ref for ref in values if ref in visible] for key, values in allowed.items()}
    input_claims = resolve_evidence_aliases({'claims': deepcopy(list(originals.values()))}, short_ids)['claims']
    proposal_context = [{key: row[key] for key in ('claimId', 'text', 'kind', 'conditions', 'designRole') if key in row}
                        for row in verification.get('accepted', [])
                        if row.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
    prompt = f'''Revise only the rejected claims below. Narrow unsupported wording or omit the claim.
Some targets have reason answer_incomplete: their existing text may be factually correct,
but omits requested aspects. Fill those omissions from that claim's allowed supplied evidence,
including necessary conditioning inputs and applicability rules; do not just shorten it.
For absence_not_established, reason from the limited positive evidence actually supplied.
Do not assert that the whole paper never reports, tests or proves something from missing
passages. A finite empirical result cannot by itself establish a universal guarantee.
Question: {question}
Accepted experimental definitions (consistency only; do not revise these or treat them as paper evidence):
{json.dumps(proposal_context, ensure_ascii=False)}
Rejected claims and checks:
{json.dumps([{'claim': row, 'check': rejected[row['claimId']]} for row in input_claims], ensure_ascii=False)}
Allowed evidence IDs per claim (candidate permissions, not proof of support):
{json.dumps({key: [short_ids[ref] for ref in values if ref in short_ids] for key, values in allowed.items()}, ensure_ascii=False)}
Exact available evidence:
{json.dumps(rows, ensure_ascii=False)}
Return a COMPACT JSON array of revised claims, or [] when no supported revision is possible.
Each revised claim uses {{"claimId":"original ID","kind":"original kind","text":"revised wording",
"evidenceRefs":["E1"],"conditions":{{}},"detailLevel":"fulltext"}}; the wording key is "text".
Keep claimId, kind and any designRole. Use only that claim's allowed evidence IDs; never turn a fact
into a proposal to evade checking. Preserve conditions needed for the narrower assertion.
Use the supplied short evidence IDs (E1, E2, ...) in both evidenceRefs and tableBindings.
Reported table numbers require tableBindings from tableData, using exactly these JSON keys:
{{"evidenceId":"E1","rowNumber":1,"groupIndex":0,"metric":"FPS","value":"200"}}
This is schema only, not evidence. Copy actual rowNumber, zero-based groupIndex, metric and value.
The key is "value", never "exactStringValue". Name dataset, method and metric beside each number.
When no verified cell is available, omit the numeric example rather than guessing a mapping.
An abstract supports only explicitly abstract-level wording (detailLevel="abstract").
Do not add new claims, searches, reported measurements or results. For an existing proposal,
you MAY specify new numeric configuration choices (seed, split, intervention level, budget,
confidence level) explicitly labeled as YOUR UNEXECUTED PROPOSAL, not as paper settings.
Complete missing protocol details rather than replacing them with "to be preregistered".
The paper need not have used a proposed setting. Keep established factual clauses restricted
to their allowed evidence. These additional passages come from the same already acquired
source versions; retrieval obligation labels do not prove relevance. Check each passage
against the actual requested aspect before citing it. Fix invalid proposed formulas and label all
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
        if not isinstance(new_refs, list) or any(ref not in allowed.get(key, []) for ref in new_refs):
            continue
        # The repair cannot reassign the claim to another research obligation.
        if 'obligationIds' in original:
            row['obligationIds'] = deepcopy(original['obligationIds'])
        # One observed provider spelling is unambiguous. Normalize syntax only;
        # the exact same identity, numeric and semantic checks still follow.
        if isinstance(row.get('claim'), str):
            if 'text' in row and row['text'] != row['claim']:
                continue
            row['text'] = row.pop('claim')
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            continue
        if original.get('designRole'):
            if row.get('designRole', original['designRole']) != original['designRole']:
                continue
            row['designRole'] = original['designRole']
        valid.append(normalize_conditions({'claims': [dict(row)]})['claims'][0])
    candidate = {'claims': [*verification.get('accepted', []), *valid]}
    limit = requested_character_limit(question)
    return [] if limit and answer_character_count(candidate) > limit else valid
