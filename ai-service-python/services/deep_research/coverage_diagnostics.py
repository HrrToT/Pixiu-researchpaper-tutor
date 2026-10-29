"""Bind actionable coverage gaps to actual audit targets, never grant support."""
from copy import deepcopy


def enabled(record):
    return (type(record.get('coverageDiagnosticsContractVersion')) is int
            and record['coverageDiagnosticsContractVersion'] in (1,2))


GUIDANCE = '''
For EACH partial/missing obligation, add gapDetail with exactly four fields:
{"criterionIds":["every partial/missing criterionId"],
 "aspectIds":["every partial/missing aspectId"],
 "missingContent":"specific content still needed in the accepted answer",
 "reason":"why the bound existing answer does not address that content"}.
IDs must exactly match the partial/missing children of THIS obligation; empty
arrays are allowed only when that child collection has no partial/missing rows.
At least one collection must identify an actual unmet target. Do not add targets,
scientific conclusions or requirements beyond the original question and its
frozen criteria. Respect the requested brevity. Explain the concrete deficiency,
not merely 'incomplete' or 'need more detail'. If a setting belongs to a different
experiment, say which relationship is missing rather than requesting an exhaustive
paper survey. Treat a clear evidence-bounded answer as sufficient for a genuine
uncertainty question; never demand a paper-wide absence claim or universal guarantee.
Each text field is nonempty and at most 800 characters. No gapDetail is permitted
for covered/not_required obligations. A partial overall status must identify an
actual partial/missing child. This explanation is an unverified review statement,
not a source fact or a command to the repairer. It does not change factual verdicts.
'''


def validate(verdicts, obligation_ids):
    """Keep partial/failed verdicts intact; reject missing or contradictory diagnostics."""
    errors, details = [], {}
    if not isinstance(verdicts,list): return ['invalid_diagnostic_rows'], details
    ids = [v.get('obligationId') if isinstance(v,dict) else None for v in verdicts]
    if (any(not isinstance(k,str) for k in ids) or len(set(ids)) != len(ids)
            or set(ids) != set(obligation_ids)):
        return ['diagnostic_obligations_not_bound'], details
    for row in verdicts:
        key = row['obligationId']; detail = row.get('gapDetail')
        if row.get('status') not in ('partial','missing'):
            if 'gapDetail' in row: errors.append(key)
            continue
        if not isinstance(detail,dict) or set(detail) != {'criterionIds','aspectIds','missingContent','reason'}:
            errors.append(key); continue
        valid = all(isinstance(detail[k],str) and detail[k].strip() and len(detail[k]) <= 800
                    for k in ('missingContent','reason'))
        has_target = False
        for name,collection,identity in (('criterionIds','criteria','criterionId'),('aspectIds','aspects','aspectId')):
            children = row.get(collection,[])
            if not isinstance(children,list) or any(not isinstance(c,dict) for c in children):
                valid = False; continue
            expected = [c.get(identity) for c in children if c.get('status') in ('partial','missing')]
            found = detail[name]
            if (not isinstance(found,list) or any(not isinstance(v,str) or not v for v in found)
                    or any(not isinstance(v,str) or not v for v in expected)):
                valid = False; continue
            if len(set(found)) != len(found) or len(set(expected)) != len(expected) or set(found) != set(expected):
                valid = False
            has_target = has_target or bool(expected)
        if valid and has_target: details[key] = deepcopy(detail)
        else: errors.append(key)
    return errors, details


def fit_complete_context(rows, render, max_bytes, required_ids):
    """Reserve complete cited rows before optional omission-detection evidence."""
    from services.deep_research.contracts import BudgetExhaustedError
    required = [r for r in rows if r['evidenceId'] in required_ids]
    if ({r['evidenceId'] for r in required} != set(required_ids)
            or len(required) != len(required_ids)):
        raise ValueError('coverage_required_evidence_missing_or_ambiguous')
    size = len(render(required).encode('utf-8'))
    if size > max_bytes:
        raise BudgetExhaustedError('coveragePromptBytes',max_bytes,size)
    selected = list(required)
    for row in rows:
        if row['evidenceId'] not in required_ids:
            trial = selected + [row]
            if len(render(trial).encode('utf-8')) <= max_bytes: selected = trial
    # Retain source order and exact fields; never remove a required context.
    selected_ids = {r['evidenceId'] for r in selected}
    selected = [r for r in rows if r['evidenceId'] in selected_ids]
    return render(selected), deepcopy(selected)
