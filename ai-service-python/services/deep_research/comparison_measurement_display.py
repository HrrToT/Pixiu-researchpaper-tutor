"""Visible exact-cell context for newly opted-in comparison drafts.

Copies coordinates already selected by the model from the server registry. It
does not select evidence, infer units, translate metrics or approve a fact.
"""
from copy import deepcopy


CONDITION = '原表测量'
ISOLATED_INPUT_BYTES = 24000


def enabled(record):
    return (record.get('state', {}).get('outputKind') == 'paper_comparison'
            and type(record.get('comparisonAuthoringContractVersion')) is int
            and record['comparisonAuthoringContractVersion'] in (1, 2, 3, 4, 5)
            and type(record.get('comparisonPlanningContractVersion')) is int
            and record['comparisonPlanningContractVersion'] == 6
            and type(record.get('comparisonReviewBatchContractVersion')) is int
            and record['comparisonReviewBatchContractVersion'] == 2)


def isolated(record):
    """New runs physically separate paper evidence from cross-paper drafting."""
    return enabled(record) and record['comparisonAuthoringContractVersion'] in (2, 3, 4, 5)


def local_contributions(record):
    """New snapshots separate global goals from per-paper assignments."""
    return enabled(record) and record['comparisonAuthoringContractVersion'] in (3, 4, 5)


def direct_scope_review(record):
    return enabled(record) and record['comparisonAuthoringContractVersion'] in (4, 5)


def referenced_repair(record):
    return enabled(record) and record['comparisonAuthoringContractVersion'] == 5


def attach(point, selected):
    """Add visible conditions only to an explicit prose branch, without edits.

    Other authored branches keep their own rendering and ordinary gates. A
    reserved condition collision is rejected, never overwritten or trusted.
    Raw model responses remain unchanged in the invocation journal.
    """
    result = deepcopy(point)
    body = result.get('body')
    if not selected or not isinstance(body, dict) or set(body) != {'prose'}:
        return result
    prose = body['prose']
    if not isinstance(prose, dict) or not isinstance(prose.get('conditions'), dict):
        return result  # Ordinary authored-body validation rejects malformed data.
    conditions = prose['conditions']
    if CONDITION in conditions:
        raise ValueError('reserved_measurement_condition')
    groups = {}
    for cell in selected:
        identity = (cell['source'], cell['group'], cell['method'])
        groups.setdefault(identity, []).append(f"{cell['binding']['metric']} {cell['binding']['value']}")
    # Do not add source titles (which may contain unrelated quantities), private
    # aliases, conversions or assumed disk/GPU-memory labels to public prose.
    conditions[CONDITION] = '；'.join(
        f"{group} / {method}：" + '，'.join(values)
        for (_, group, method), values in groups.items())
    return result


def refresh(claim, evidence):
    """Rebuild a repaired prose condition from its own exact retained bindings.

    This verifies display identity only. Invalid bindings remain for ordinary
    rejection; they never acquire generated conditions. A forged display field
    is not overwritten into apparently valid output.
    """
    from services.deep_research.table_bindings import bound_table_context
    if isinstance(claim.get('scopeExpression'), dict):
        return deepcopy(claim)
    bindings = claim.get('tableBindings') or []
    cells = bound_table_context(claim, evidence)
    if len(cells) != len(bindings):
        return deepcopy(claim)
    by_id = {e['evidenceId']: e for e in evidence if e['evidenceId'] in claim.get('evidenceRefs', [])}
    selected = [{**cell, 'binding': binding,
                 'source': (by_id[binding['evidenceId']].get('sourceWorkId'),
                            by_id[binding['evidenceId']].get('sourceVersionId'))}
                for cell, binding in zip(cells, bindings)]
    conditions = deepcopy(claim.get('conditions') or {})
    declared = conditions.pop(CONDITION, None)
    point = attach({'body': {'prose': {'text': claim['text'], 'conditions': conditions}}}, selected)
    new = point['body']['prose']['conditions']
    if declared is not None and declared != new.get(CONDITION):
        raise ValueError('Conflicting repaired measurement display')
    return {**deepcopy(claim), 'conditions': new}
