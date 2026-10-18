"""Exact quantity spelling equivalence; never changes a quoted source."""
from __future__ import annotations

import re
from decimal import Decimal


_SCALES = {'十': 1, '百': 2, '千': 3, '万': 4, '十万': 5, '百万': 6,
           '千万': 7, '亿': 8, '十亿': 9, '百亿': 10, '千亿': 11, '万亿': 12}
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_.,])(?P<number>[-+]?\d(?:[\d,]*\d)?(?:\.[\d,]*\d)?(?:[eE][-+]?\d+)?)'
    r'(?:\s*(?P<scale>万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百|十))?'
    r'(?:\s*(?P<unit>[%％x×倍]))?')
_VALID_NUMBER = re.compile(
    r'(?P<sign>[-+]?)(?P<integer>\d+|\d{1,3}(?:,\d{3})+)'
    r'(?:\.(?P<fraction>\d+))?(?:[eE](?P<exponent>[-+]?\d+))?\Z')
_WORDS = dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'), range(13)))
_WORD_COUNTS = re.compile(r'(?<![A-Za-z0-9_])(?:(?P<sign>minus|negative|plus|positive|[-−+])\s*)?'
    r'(?P<word>zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
    r'[\s\-‐‑–]+(?:dimensions?|dimensional|components?|channels?|outputs?|views?|frames?|images?|'
    r'samples?|trials?|runs?|scenes?|layers?|stages?|phases?|steps?|seeds?|points?|iterations?|groups?)\b', re.I)
_CHINESE_COUNTS = re.compile(r'(?<![A-Za-z0-9_第零一二两三四五六七八九十百千万亿点.])'
    r'(?P<sign>[负正+＋\-−])?\s*(?P<word>[零一二两三四五六七八九十]{1,3})\s*'
    r'(?:个|维|次|帧|层|组|张|条|篇|种|项)')


def _chinese_count(word):
    values = dict(zip('零一二两三四五六七八九', (0,1,2,2,3,4,5,6,7,8,9)))
    if word in values: return values[word]
    if word == '十': return 10
    if word in ('十一', '十二'): return 10 + values[word[1]]
    return None


def _count_words(text, *, relative_references=False):
    for match in _WORD_COUNTS.finditer(text):
        # Do not misread the tail of an unsupported compound (twenty-three)
        # as three, or invent the number of the remaining dimensions.
        if re.search(r'[A-Za-z][\-‐‑–]\s*$', text[:match.start('word')]): continue
        value = _WORDS[match['word'].lower()]
        yield -value if (match['sign'] or '').lower() in {'minus','negative','-','−'} else value
    for match in _CHINESE_COUNTS.finditer(text):
        # 上一帧/下一组 locate an adjacent item; they do not report its count.
        # Keep 前两帧/后四组 and all signed counts as actual quantities.
        if (relative_references and match['word'] == '一' and not match['sign']
                and re.search(r'[上下前后]\s*$', text[:match.start('word')])):
            continue
        value = _chinese_count(match['word'])
        if value is not None:
            yield -value if match['sign'] in {'负','-','−'} else value


def number_display(identity):
    """Readable exact check detail; do not expand hostile/large exponents."""
    match = re.fullmatch(r'(-?\d+)e(-?\d+)([%x]?)', identity)
    if not match: return identity
    coefficient, exponent, unit = match.groups()
    if len(coefficient) <= 24 and len(exponent) <= 3 and -6 <= int(exponent) <= 8:
        return format(Decimal(coefficient + 'e' + exponent), 'f') + unit
    return identity


def measurement_numbers(text: str, *, word_counts=False, relative_references=False) -> set[str]:
    """Compare decimal/scientific/grouped/Chinese-scale forms exactly.

    Store a coefficient and exponent, without float rounding, Decimal context
    rounding or expanding large exponents. Malformed comma groups stay opaque;
    their pieces must not accidentally support an unrelated smaller number.
    Percentages and factors retain distinct identities. Other physical units
    and the relation between quantities still require semantic verification.
    Opt-in count words recognize directly written zero-to-twelve quantities
    beside count nouns. They do not infer remaining counts or evaluate sums.
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
    if word_counts is True:
        for value in _count_words(text, relative_references=relative_references):
            numbers.update(measurement_numbers(str(value)))
    return numbers
