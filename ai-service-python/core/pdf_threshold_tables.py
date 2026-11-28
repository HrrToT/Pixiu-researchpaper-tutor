"""Verify threshold columns in a ruled table against its PDF and extracted text."""
from bisect import bisect_right
from collections import Counter, defaultdict
from decimal import Decimal
import re
from statistics import median

from core.pdf_benchmark_columns import _compact, _line_groups, _tokens

_CAPTION = re.compile(r'^Table\s*(\d+)\s*[:.]', re.I)
_VALUE = re.compile(r'[+−-]?(?:\d+(?:\.\d+)?|\.\d+)')
_THRESHOLD = re.compile(r'([εϵτ])=(\d+(?:\.\d+)?)')
_GLYPHS = {b'epsilon': 'ε', b'epsilon1': 'ϵ', b'tau': 'τ'}


def _ruled_tables(runs, rules, text):
    plain = Counter(_compact(line) for line in text.splitlines())
    frames = defaultdict(set)
    for left, right, y in rules:
        if right - left >= 100:
            frames[round(left, 2), round(right, 2)].add(round(y, 2))
    for (left, right), levels in frames.items():
        levels = sorted(levels)
        for top, middle, divider, bottom in zip(levels, levels[1:], levels[2:], levels[3:]):
            if not (7 <= middle - top <= 30 and 7 <= divider - middle <= 30 and 12 <= bottom - divider <= 150):
                continue
            group = _line_groups([row for row in runs if left - 1 <= row['x'] <= right + 1
                                  and top < row['y'] < bottom])
            if not 4 <= len(group) <= 32:
                continue
            upper, lower, *body = group
            if not upper[0]['y'] < middle < lower[0]['y'] < divider < body[0][0]['y']:
                continue
            packet = _threshold_columns(upper, lower, body, plain)
            if not packet:
                continue
            captions = _line_groups([row for row in runs if left - 12 <= row['x'] <= right + 25
                                     and bottom < row['y'] <= bottom + 25])
            if not captions:
                continue
            caption = ' '.join(token['text'] for token in _tokens(captions[0]))
            match = _CAPTION.match(caption)
            if match and plain[_compact(caption)] == 1:
                yield {'number': match[1], 'caption': caption, 'tableData': packet, 'thresholdProjection': True}


def _threshold_columns(upper, lower, body, plain):
    rows = [_tokens(line) for line in body]
    width = min(map(len, rows))
    if not 3 <= width <= 16 or any(len(row) != width for row in rows):
        return None
    centers = [median(token['x'] for token in col) for col in zip(*rows, strict=True)]
    if any(right - left < 9 for left, right in zip(centers, centers[1:])):
        return None
    midpoints = [(left + right) / 2 for left, right in zip(centers, centers[1:])]

    def column(token):
        return bisect_right(midpoints, token['x'])

    values = [[t['text'] for t in row] for row in rows]
    if (any(abs(t['x'] - centers[i]) > 3 for row in rows for i, t in enumerate(row) if i)
            or len({row[0] for row in values}) != len(rows)
            or any(not re.search(r'[A-Za-z]', row[0]) or not all(_VALUE.fullmatch(v) for v in row[1:])
                   or plain[_compact(''.join(row))] != 1 for row in values)):
        return None
    headers = _tokens(lower)
    heading = _tokens(upper)
    if not headers or not heading or plain[_compact(''.join(t['text'] for t in headers))] != 1:
        return None
    thresholds = []
    for i, token in enumerate(headers):
        if token['text'] not in ('ε', 'ϵ', 'τ'):
            continue
        # A right-aligned digit may fall just across the midpoint of the
        # narrow cell. Bind the symbol's origin and contiguous printed triplet.
        triplet = headers[i:i + 3]
        match = _THRESHOLD.fullmatch(''.join(t['text'] for t in triplet))
        if not match or not 0 < triplet[-1]['x'] - token['x'] <= 20:
            return None
        thresholds.append((column(token), match, token['x']))
    cols = [i for i, _, _ in thresholds]
    if (not 2 <= len(cols) <= 8 or cols != list(range(1, 1 + len(cols)))
            or len({match[1] for _, match, _ in thresholds}) != 1
            or any(abs(x - centers[i]) > 5 for i, _, x in thresholds)):
        return None
    levels = [Decimal(match[2]) for _, match, _ in thresholds]
    if any(right <= left for left, right in zip(levels, levels[1:])):
        return None
    label = ' '.join(t['text'] for t in heading if column(t) in cols)
    if (not re.search(r'[A-Za-z]', label) or plain[_compact(''.join(t['text'] for t in heading))] != 1
            or any(column(t) == 0 for t in heading)
            or (len(cols) + 1 < width and not any(column(t) == len(cols) + 1 for t in heading))):
        return None

    # Canonical numeric spelling in the structured projection. The page text
    # and its original leading-dot representation are preserved independently.
    return {'groups': [[label, [match[0] for _, match, _ in thresholds]]],
            'rows': [[number, row[0], [re.sub(r'^([+−-]?)\.', r'\g<1>0.', row[i]) for i in cols]]
                     for number, row in enumerate(values, 2)]}


def verified_threshold_tables(page, text):
    if page.get('/Rotate', 0) % 360 or not re.search(r'[εϵτ]\s*=\s*\d', text):
        return []
    from core.pdf_model_table import horizontal_rules
    from core.pdf_table_columns import drawing_runs

    tables = list(_ruled_tables(drawing_runs(page, named_glyphs=_GLYPHS), horizontal_rules(page), text))
    counts = Counter(table['number'] for table in tables)
    return [table for table in tables if counts[table['number']] == 1]
