"""Unactivated ordered-metadata prototype; not a repair of historical output.

The existing lifecycle checker already imposes the phase array's total order.
This wire removes the duplicate `after` relation and expresses allocation before
an authored phase. Lowering neither reorders phases nor chooses an allocation.
All operations, reads, groups, budgets and other values remain authored data.
"""
from copy import deepcopy

from services.deep_research.workflow_metadata_rows import COMMON, PHASE_COLUMNS, _json_copy

NAME = 'ordered_workflow_metadata_v1'
PHASE_FIELDS = tuple(k for k in PHASE_COLUMNS if k != 'after')


def complete_scaffolding(value):
    try:
        value = _json_copy(value)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return False
    if (not isinstance(value, dict) or set(value) != {*COMMON, 'components', 'phases'}
            or not isinstance(value['components'], list) or len(value['components']) > 8
            or not isinstance(value['phases'], list) or not 1 <= len(value['phases']) <= 128):
        return False
    ids = []
    for p in value['phases']:
        if (not isinstance(p, dict) or set(p) != set(PHASE_FIELDS)
                or not isinstance(p['phaseId'], str) or not p['phaseId'] or p['phaseId'] in ids):
            return False
        ids.append(p['phaseId'])
    for c in value['components']:
        if not isinstance(c, dict) or set(c) != {'componentId', 'appliesTo', 'lifecycle'}:
            return False
        life = c['lifecycle']
        if (not isinstance(life, dict) or set(life) != {'scope', 'createBefore', 'disposeAfter'}
                or not isinstance(life['createBefore'], str) or life['createBefore'] not in ids):
            return False
    return True


def decode(value):
    if not complete_scaffolding(value):
        raise ValueError('Incomplete, ambiguous, or non-ordered metadata wire')
    result = _json_copy(value)
    ids = [p['phaseId'] for p in result['phases']]
    first_frame = next((i for i, p in enumerate(result['phases']) if p['scope'] == 'per_frame'), 0)
    for c in result['components']:
        life = c['lifecycle']
        index = ids.index(life.pop('createBefore'))
        if life['scope'] == 'per_frame' and index < first_frame:
            # The canonical event model clamps per-frame creation to the
            # frame-block entrance. Do not silently move an authored boundary.
            raise ValueError('Cannot move authored allocation to the frame entrance')
        life['createAfter'] = [ids[index - 1]] if index else []
    for p in result['phases']:
        # No extra edge is needed: the canonical checker already orders all
        # events by array position. No operation or source reference is inferred.
        p['after'] = []
    return result


def descriptor():
    from services.deep_research.workflow_units import descriptor as canonical_descriptor, META
    result = deepcopy(canonical_descriptor(META, 7))
    result['name'] = NAME
    defs = result['schema']['$defs']
    phase = defs['phase']
    del phase['properties']['after']
    phase['required'].remove('after')
    life = defs['lifecycle']
    del life['properties']['createAfter']
    life['properties']['createBefore'] = {'type': 'string', 'minLength': 1}
    life['required'] = ['scope', 'createBefore', 'disposeAfter']
    return result
