from copy import deepcopy
import json

import pytest

from services.deep_research.repair_bound_values import encode, restore, render, KEY


def fixture():
    value = {'states': [{'name': '中文🙂', 'shape': [0, False, None], 'values': list(range(120))}]}
    claims = [{'claimId': 'c', 'executionSpec': value}]
    finding = {'kind': 'incomplete', 'claimId': 'c', 'path': ['executionSpec'],
               'value': deepcopy(value), 'reason': '未解决的问题，必须保留。'}
    return claims, {'c': {'detail': '原始问题', 'rejectionAudit': {'findings': [finding]}}}


def test_exact_bound_values_roundtrip_without_mutating_originals_or_approving_findings():
    claims, checks = fixture()
    before = deepcopy((claims, checks))
    packet, count = encode(checks, claims)
    assert count == 1
    assert packet['c']['rejectionAudit']['findings'][0]['value'] == {KEY: True}
    assert restore(packet, claims) == checks
    assert (claims, checks) == before


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'value', 'path', 'bool_path', 'absent'])
def test_never_guesses_or_rebinds_a_mismatched_field(change):
    claims, checks = fixture()
    f = checks['c']['rejectionAudit']['findings'][0]
    if change == 'unknown': f['claimId'] = 'other'
    elif change == 'duplicate': claims.append(deepcopy(claims[0]))
    elif change == 'value': f['value']['states'][0]['values'][0] = False
    elif change == 'path': f['path'] = ['not_supplied']
    elif change == 'bool_path': f['path'] = ['executionSpec', True]
    else: f['kind'] = 'missing_field'
    assert encode(checks, claims) == (checks, 0)


def test_literal_marker_collision_keeps_all_original_data():
    claims, checks = fixture()
    checks['literal'] = {KEY: True}
    assert encode(checks, claims) == (checks, 0)


@pytest.mark.parametrize('change', ['false', 'zero', 'extra', 'unknown', 'path', 'unscoped'])
def test_invalid_marker_never_resolves_to_a_guessed_value(change):
    claims, checks = fixture()
    packet, _ = encode(checks, claims)
    f = packet['c']['rejectionAudit']['findings'][0]
    if change == 'false': f['value'][KEY] = False
    elif change == 'zero': f['value'][KEY] = 0
    elif change == 'extra': f['value']['extra'] = 1
    elif change == 'unknown': f['claimId'] = 'other'
    elif change == 'path': f['path'] = ['executionSpec', 'missing']
    else: packet['extra'] = {KEY: True}
    with pytest.raises(ValueError): restore(packet, claims)


def test_complete_render_must_save_bytes_after_legend_overhead(monkeypatch):
    import services.deep_research.repair_check_text as literal
    monkeypatch.setattr(literal, 'render', lambda **kw: json.dumps(kw['checks'], ensure_ascii=False))
    claims, checks = fixture()
    kw = {'targets': claims, 'accepted': [], 'siblings': [], 'checks': checks}
    assert KEY in render(**kw)
    # A valid reference that saves less than its instructions must stay literal.
    value = {'payload': 'x' * 101}
    claims[0]['executionSpec'] = value
    checks['c']['rejectionAudit']['findings'][0]['value'] = value
    assert render(**kw) == literal.render(**kw)
