"""Verify two-line benchmark headers and complete data rows against PDF drawing positions."""
from collections import Counter
import re
from statistics import median
import unicodedata


_NUMBER = r'[-+−]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|[KMB])?'
_NUMERIC_CELL = re.compile(rf'{_NUMBER}(?:/{_NUMBER}){{0,3}}')


def _compact(value):
    return ''.join(unicodedata.normalize('NFKC', value).split())


def _line_groups(runs):
    lines = []
    for run in sorted(runs, key=lambda item: (item['y'], item['x'])):
        if not lines or run['y'] - lines[-1][0]['y'] > 1.5:
            lines.append([])
        lines[-1].append(run)
    return lines


def _tokens(line):
    if any(not run.get('tokens') for run in line):
        return []
    return sorted((token for run in line for token in run['tokens']), key=lambda token: token['x'])


def verify_two_tier_columns(section, runs):
    """Recover only independently drawn columns and unambiguous matching TEI rows."""
    bounds = section.get('tableBounds')
    header, *rows = section.get('tableRows') or [[]]
    if not bounds or len(header) < 2 or any(cell['rows'] != 1 for cell in header):
        return None
    width = sum(cell['cols'] for cell in header)
    if not 3 <= width <= 12:
        return None
    x, y, w, h = bounds
    lines = _line_groups([run for run in runs if x - 2 <= run['x'] <= x + w + 2
                          and y - 2 <= run['y'] <= y + h + 2])
    if not lines:
        return None
    drawing_rows = []
    for line in lines:
        tokens = _tokens(line)
        if len(tokens) < width:
            continue
        label = _compact(''.join(token['text'] for token in tokens[:1 - width]))
        values = tuple(_compact(token['text']) for token in tokens[1 - width:])
        if label and all(_NUMERIC_CELL.fullmatch(value) for value in values):
            drawing_rows.append(((label, *values), line[0]['y'], [token['x'] for token in tokens[1 - width:]]))

    eligible_rows = [(number, [cell['text'] for cell in row]) for number, row in enumerate(rows, 2)
                     if len(row) == width and all(cell['rows'] == cell['cols'] == 1 for cell in row)]
    # Row labels can repeat across parameter scales. Use the complete row as
    # the identity, and require a unique match on both sides.
    tei_count = Counter(tuple(map(_compact, cells)) for _, cells in eligible_rows)
    physical_count = Counter(entry[0] for entry in drawing_rows)
    unique = {entry[0]: entry[1:] for entry in drawing_rows if physical_count[entry[0]] == 1}
    matches = []
    for number, cells in eligible_rows:
        key = tuple(map(_compact, cells))
        if tei_count[key] == 1 and key in unique:
            matches.append((number, cells, *unique[key]))
    if len(matches) < 2:
        return None

    centers = [median(column) for column in zip(*(entry[3] for entry in matches), strict=True)]
    gaps = [right - left for left, right in zip(centers, centers[1:])]
    if min(gaps) < 12:
        return None
    bounds_x = [min(entry[3][0] for entry in matches) - gaps[0] / 2,
                *((a + b) / 2 for a,b in zip(centers, centers[1:])), x + w + 2]
    stable = [entry for entry in matches if all(left <= value < right for value, left, right
              in zip(entry[3], bounds_x, bounds_x[1:]))]
    if len(stable) < 2:
        return None
    first_row_y = min(row[1] for row in drawing_rows)
    header_lines = [line for line in lines if line[0]['y'] < first_row_y - 3]
    if any(not _tokens(line) for line in header_lines):
        return None
    # Group labels come from two common PDF baselines. TEI corroborates the
    # literal words but its merged cells never assign column ownership.
    header_text = _compact(' '.join(cell['text'] for cell in header)).casefold()
    if not any(_compact(''.join(token['text'] for token in _tokens(line)
                       if token['x'] < bounds_x[0])).casefold() == _compact(header[0]['text']).casefold()
               for line in header_lines):
        return None
    groups = []
    anchors = None
    for left, right in zip(bounds_x, bounds_x[1:]):
        cell_lines = []
        for line in header_lines:
            value = ' '.join(token['text'] for token in _tokens(line) if left <= token['x'] < right)
            if value:
                cell_lines.append((line[0]['y'], value))
        if len(cell_lines) != 2:
            return None
        baselines = tuple(item[0] for item in cell_lines)
        if anchors is not None and baselines != anchors:
            return None
        anchors = baselines
        label, metric = (item[1] for item in cell_lines)
        if not all(re.search('[A-Za-z]', value) and _compact(value).casefold() in header_text
                   for value in (label, metric)):
            return None
        groups.append([label, [metric]])
    if len({_compact(g[0]).casefold() for g in groups}) != len(groups):
        return None
    return {'groups': groups, 'rows': [[number, cells[0], cells[1:]] for number, cells, _, _ in stable]}


_PERCENT = re.compile(r'\d+(?:\.\d+)?%')


def ruled_percentage_tables(runs, rules, plain_text):
    """Recover repeated percentage columns when TEI merged or omitted the table."""
    from bisect import bisect_right
    from collections import defaultdict

    from core.pdf_table_columns import _physical_table_caption

    plain_lines = Counter(_compact(line) for line in plain_text.splitlines())
    wide_rules = defaultdict(set)
    for left, right, y in rules:
        if right - left >= 120:
            wide_rules[round(left, 1), round(right, 1)].add(round(y, 2))

    for (left, right), levels in wide_rules.items():
        levels = sorted(levels)
        for top, divider, bottom in zip(levels, levels[1:], levels[2:]):
            if not 12 <= divider - top <= 55 or not 12 <= bottom - divider <= 140:
                continue
            bands = sorted({(round(a, 2), round(b, 2), round(y, 2)) for a, b, y in rules
                            if left <= a < b <= right and top < y < divider and 18 <= b - a < 120})
            if not 2 <= len(bands) <= 6 or len({band[2] for band in bands}) != 1:
                continue
            if any(a[1] >= b[0] for a, b in zip(bands, bands[1:])):
                continue
            lines = _line_groups([run for run in runs if left - 1 <= run['x'] < right + 1
                                   and top < run['y'] < bottom])
            if len(lines) < 5 or any(not _tokens(line) for line in lines):
                continue
            first, fixed, leaves, *body = lines
            if not first[0]['y'] < bands[0][2] < leaves[0]['y'] < divider < body[0][0]['y']:
                continue
            if abs(fixed[0]['y'] - bands[0][2]) > 3:
                continue
            drawn_rows = [_tokens(line) for line in body]
            width = len(drawn_rows[0])
            if not 5 <= width <= 20 or any(len(row) != width for row in drawn_rows):
                continue
            centers = [median(token['x'] for token in column) for column in zip(*drawn_rows, strict=True)]
            if any(b - a < 9 for a, b in zip(centers, centers[1:])):
                continue
            boundaries = [(a + b) / 2 for a, b in zip(centers, centers[1:])]

            def column(token):
                return bisect_right(boundaries, token['x'])

            rows = [[token['text'] for token in row] for row in drawn_rows]
            if (any([column(token) for token in row] != list(range(width)) for row in drawn_rows)
                    or any(not all(_NUMERIC_CELL.fullmatch(value) for value in row[1:]) for row in rows)
                    or any(plain_lines[_compact(''.join(row))] != 1 for row in rows)
                    or len({row[0] for row in rows}) != len(rows)):
                continue

            groups = _percentage_header_groups(first, fixed, leaves, bands, centers, column)
            if groups is None:
                continue
            bounds = [left, top, right - left, bottom - top]
            caption = _physical_table_caption({'tableBounds': bounds}, runs, two_tier=True)
            if not caption or not any(re.match(r'^\s*Table\s*' + caption['number'] + r'[.:]', run['text'], re.I)
                                      and 0 < run['y'] - bottom <= 25 and left - 2 <= run['x'] <= right
                                      for run in runs):
                continue
            yield bounds, caption, groups, rows


def _percentage_header_groups(first, fixed, leaves, bands, centers, column):
    upper, fixed_labels, lower = map(_tokens, (first, fixed, leaves))
    grouped = []
    for left, right, _ in bands:
        columns = [i for i, center in enumerate(centers) if left - 2 <= center <= right + 2]
        label = ' '.join(token['text'] for token in upper if left - 2 <= token['x'] <= right + 2)
        tokens = [token for token in lower if left - 2 <= token['x'] <= right + 2]
        values = [token['text'] for token in tokens]
        if (len(columns) < 2 or [column(token) for token in tokens] != columns
                or any(not _PERCENT.fullmatch(value) for value in values)
                or len(set(values)) != len(values) or not re.search('[A-Za-z]', label)):
            return None
        grouped.append((columns, label, values))
    first_group_column = grouped[0][0][0]
    if (first_group_column < 2 or [i for columns, _, _ in grouped for i in columns]
            != list(range(first_group_column, len(centers)))
            or len({_compact(label).casefold() for _, label, _ in grouped}) != len(grouped)
            or any(sum(left - 2 <= token['x'] <= right + 2 for left, right, _ in bands) != 1 for token in upper)
            or any(sum(left - 2 <= token['x'] <= right + 2 for left, right, _ in bands)
                   != (column(token) >= first_group_column) for token in lower)
            or any(column(token) >= first_group_column for token in fixed_labels)):
        return None
    labels = []
    for i in range(first_group_column):
        primary = [token['text'] for token in fixed_labels if column(token) == i]
        if not primary:
            return None
        qualifier = [token['text'] for token in lower if column(token) == i]
        labels.append(' '.join(primary + qualifier))
    return [['', labels[1:]], *[[label, values] for _, label, values in grouped]]
