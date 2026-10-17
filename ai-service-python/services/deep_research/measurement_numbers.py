"""Exact quantity spelling equivalence; never changes a quoted source."""
from __future__ import annotations

import re


_SCALES = {'十': 1, '百': 2, '千': 3, '万': 4, '十万': 5, '百万': 6,
           '千万': 7, '亿': 8, '十亿': 9, '百亿': 10, '千亿': 11, '万亿': 12}
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_.,])(?P<number>[-+]?\d(?:[\d,]*\d)?(?:\.[\d,]*\d)?(?:[eE][-+]?\d+)?)'
    r'(?:\s*(?P<scale>万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百|十))?'
    r'(?:\s*(?P<unit>[%％x×倍]))?')
_VALID_NUMBER = re.compile(
    r'(?P<sign>[-+]?)(?P<integer>\d+|\d{1,3}(?:,\d{3})+)'
    r'(?:\.(?P<fraction>\d+))?(?:[eE](?P<exponent>[-+]?\d+))?\Z')


def measurement_numbers(text: str) -> set[str]:
    """Compare decimal/scientific/grouped/Chinese-scale forms exactly.

    Store a coefficient and exponent, without float rounding, Decimal context
    rounding or expanding large exponents. Malformed comma groups stay opaque;
    their pieces must not accidentally support an unrelated smaller number.
    Percentages and factors retain distinct identities. Other physical units
    and the relation between quantities still require semantic verification.
    """
    numbers = set()
    for match in _NUMBER.finditer(text):
        literal = match.group('number')
        parsed = _VALID_NUMBER.fullmatch(literal)
        exponent_text = parsed.group('exponent') if parsed else None
        # Bound conversion of hostile exponents, not the expanded number size.
        # Unsupported spellings can match themselves, but gain no equivalence.
        if (not parsed or (exponent_text and len(exponent_text.lstrip('+-')) > 9)
                or text[match.end():].startswith('分之')):
            numbers.add('literal:' + match.group())
            continue
        fraction = parsed.group('fraction') or ''
        coefficient = (parsed.group('integer').replace(',', '') + fraction).lstrip('0')
        exponent = int(exponent_text or '0') - len(fraction) + _SCALES.get(match.group('scale'), 0)
        if coefficient:
            trimmed = coefficient.rstrip('0')
            exponent += len(coefficient) - len(trimmed)
            coefficient = ('-' if parsed.group('sign') == '-' else '') + trimmed
        else:
            coefficient, exponent = '0', 0
        unit = match.group('unit')
        suffix = '%' if unit in {'%', '％'} else 'x' if unit in {'x', '×', '倍'} else ''
        numbers.add(f'{coefficient}e{exponent}{suffix}')
    return numbers
