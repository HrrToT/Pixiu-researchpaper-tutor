"""Keep reader edits within their existing frozen question assignments."""
from copy import deepcopy
import json


def manifest(report, requirements, protected_ids):
    if not isinstance(requirements, (list, tuple)):
        raise ValueError('Invalid reader requirements')
    by_id = {}
    for row in requirements:
        oid = row.get('obligationId') if isinstance(row, dict) else None
        if not isinstance(oid, str) or not oid or oid in by_id:
            raise ValueError('Ambiguous reader requirement identity')
        by_id[oid] = row
    editable, fixed = [], []
    for claim in report['claims']:
        ids = claim.get('obligationIds')
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(k, str) or k not in by_id for k in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Reader target has unresolved question assignments')
        row = {'claimId': claim['claimId'], 'obligationIds': deepcopy(ids)}
        (fixed if claim['claimId'] in protected_ids else editable).append(row)
    owned = {oid for row in editable for oid in row['obligationIds']}
    fixed_only = list(dict.fromkeys(oid for row in fixed for oid in row['obligationIds'] if oid not in owned))
    relevant = owned | set(fixed_only)
    return {'editableTargets': editable, 'fixedTargets': fixed,
            'fixedOnlyObligationIds': fixed_only,
            'requestedPoints': [{k: deepcopy(row[k]) for k in
                ('obligationId', 'question', 'completionCriteria', 'requiredSources') if k in row}
                for oid, row in by_id.items() if oid in relevant]}


def append(prompt, report, requirements, protected_ids):
    assignments = manifest(report, requirements, protected_ids)
    return prompt + '''
Reader responsibility map (UNVERIFIED draft assignments, not evidence of coverage):
''' + json.dumps(assignments, ensure_ascii=False, separators=(',', ':')) + '''
The whole question supplies global constraints, not permission to answer every part
again in each editable target. For each editable target explain its own assigned
requested points. fixedOnlyObligationIds are assigned exclusively to server-retained
points: do not repeat their answer or add a new conclusion about them in editable prose.
A shared obligation is NOT fixed-only; preserve the editable target's own requested
role where assignments overlap. Do not drop an assigned requested aspect to save words.
Keep necessary scientific conditions on the mechanism you actually explain. Avoiding
an unsupported guarantee does not require adding a guarantee-denial sentence to every
point. The map does not prove any answer correct, complete or supported. An unresolved
fixed point remains unresolved; never manufacture its answer in a different target.
Do not change IDs, kinds, source permissions or assignments. Own original sources,
independent factual checks and whole-answer coverage remain mandatory.
'''
