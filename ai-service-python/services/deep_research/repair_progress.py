"""Do not re-roll a failed factual verdict without changed content or evidence."""
import json


def enabled(record):
    return (type(record.get('repairProgressContractVersion')) is int
            and record['repairProgressContractVersion'] == 1)


def _identity(claim):
    def stable(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return (
        claim.get('kind'), ' '.join(claim.get('text', '').split()),
        stable(claim.get('conditions') or {}),
        tuple(sorted(set(claim.get('evidenceRefs') or []))),
        claim.get('detailLevel', 'fulltext'),
        tuple(sorted(stable(row) for row in claim.get('tableBindings') or [])),
    )


def partition_revisions(report, verification, revised):
    """Only unchanged, semantically rejected facts are withheld here.

    New wording/conditions, a changed cited passage or a corrected table binding
    still goes through all normal checks; none is accepted by this helper.
    Proposals keep their shared context checks because a sibling definition may
    have been corrected without changing this proposal's own text.
    """
    originals = {row['claimId']: row for row in report.get('claims', [])}
    rejections = {row['claimId']: row for row in verification.get('rejected', [])}
    candidates, retained = [], []
    for row in revised:
        key = row.get('claimId')
        before, rejection = originals.get(key), rejections.get(key)
        if (before and rejection and before.get('kind') in {'reported', 'inference'}
                and rejection.get('reason') == 'semantic_unresolved'
                and _identity(before) == _identity(row)):
            retained.append({**rejection, 'reason': 'unchanged_semantic_rejection',
                'originalReason': rejection['reason'],
                'progressDetail': '论断内容和引用依据未变，保留原核验拒绝结果。'})
        else:
            candidates.append(row)
    return candidates, retained
