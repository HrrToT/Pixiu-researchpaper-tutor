"""Repair5: reference only exactly matching, already supplied finding values."""
from collections import Counter
from copy import deepcopy
import json

KEY = '$boundValue'
LEGEND = ('\nOnly in rejection findings, value:{"$boundValue":true} is the EXACT value '
          'at that finding claimId/path in supplied original targets/consistency context. '
          'Expand tables and check-text dictionary before resolving; retain every character/type. References add no '
          'source permission or scientific approval.\n')


def _index(claims):
    counts = Counter(c.get('claimId') for c in claims if isinstance(c, dict)
                     and isinstance(c.get('claimId'), str))
    return {c['claimId']: c for c in claims if isinstance(c, dict)
            and isinstance(c.get('claimId'), str) and counts[c['claimId']] == 1}


def _value(finding, claims):
    from services.deep_research.rejection_audit import _lookup
    path, cid = finding.get('path'), finding.get('claimId')
    if (finding.get('kind') not in ('incomplete', 'incompatible', 'unsupported')
            or not isinstance(cid, str) or cid not in claims or not isinstance(path, list)
            or not 1 <= len(path) <= 12 or path[0] not in ('text', 'conditions', 'executionSpec')
            or any(not isinstance(k, str) and type(k) is not int for k in path)):
        return False, None
    return _lookup(claims[cid], path)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def encode(checks, claims):
    def collision(value):
        return (isinstance(value, dict) and (KEY in value or any(collision(v) for v in value.values()))
                or isinstance(value, list) and any(collision(v) for v in value))
    if collision(checks):
        return deepcopy(checks), 0
    index, count = _index(claims), 0

    def visit(value):
        nonlocal count
        if isinstance(value, list):
            return [visit(v) for v in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        result = {k: visit(v) for k, v in value.items()}
        exists, original = _value(value, index)
        if exists and 'value' in value:
            try:
                exact = _json(original) == _json(value['value'])
                profitable = len(_json(original).encode('utf8')) > 100
            except (TypeError, ValueError, OverflowError):
                exact = profitable = False
            if exact and profitable:
                result['value'] = {KEY: True}
                count += 1
        return result

    packed = visit(checks)
    if count and _json(restore(packed, claims)) != _json(checks):
        raise ValueError('Repair bound values do not roundtrip')
    return packed, count


def restore(checks, claims):
    index = _index(claims)

    def visit(value):
        if isinstance(value, list):
            return [visit(v) for v in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        if KEY in value:
            raise ValueError('Unscoped repair value reference')
        marker = value.get('value')
        bound = isinstance(marker, dict) and KEY in marker
        if bound:
            exists, original = _value(value, index)
            if set(marker) != {KEY} or marker[KEY] is not True or not exists:
                raise ValueError('Invalid repair value reference')
        return {k: deepcopy(original) if bound and k == 'value' else visit(v)
                for k, v in value.items()}

    return visit(checks)


def render(**kwargs):
    from services.deep_research.repair_check_text import render as literal
    original = literal(**kwargs)
    claims = [*kwargs['targets'], *kwargs['accepted'], *kwargs['siblings']]
    checks, count = encode(kwargs['checks'], claims)
    if not count:
        return original
    candidate = literal(**{**kwargs, 'checks': checks}) + LEGEND
    # Include dictionary/grammar/legend overhead, not just substituted values.
    return candidate if len(candidate.encode('utf8')) < len(original.encode('utf8')) else original
