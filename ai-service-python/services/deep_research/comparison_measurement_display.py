"""Visible exact-cell context for newly opted-in comparison drafts.

Copies coordinates already selected by the model from the server registry. It
does not select evidence, infer units, translate metrics or approve a fact.
"""
from copy import deepcopy


CONDITION = '原表测量'


def enabled(record):
    return (type(record.get('comparisonAuthoringContractVersion')) is int
            and record['comparisonAuthoringContractVersion'] == 1
            and type(record.get('comparisonPlanningContractVersion')) is int
            and record['comparisonPlanningContractVersion'] == 6
            and type(record.get('comparisonReviewBatchContractVersion')) is int
            and record['comparisonReviewBatchContractVersion'] == 2)


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
