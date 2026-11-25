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
