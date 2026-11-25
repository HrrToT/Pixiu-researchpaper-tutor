"""Verify benchmark tables with a model label spanning configuration rows."""
from collections import Counter

from core.pdf_benchmark_columns import _NUMERIC_CELL, _compact, _line_groups, _tokens


def horizontal_rules(page):
    """Return painted, unskewed horizontal segments in top-down page coordinates."""
    point, path, rules = None, [], []
    height = float(page.mediabox.height)

    def before(operator, operands, cm, _tm):
        nonlocal point
        if operator in (b'm', b'l') and len(operands) == 2 and not (cm[1] or cm[2]):
            x, y = map(float, operands)
            next_point = (x * cm[0] + cm[4], height - (y * cm[3] + cm[5]))
            if operator == b'l' and point and abs(point[1] - next_point[1]) < 0.3:
                path.append((*sorted((point[0], next_point[0])), point[1]))
            point = next_point
        elif operator in (b'S', b's', b'B', b'B*', b'b', b'b*', b'n', b'f', b'f*', b'F'):
            if operator in (b'S', b's', b'B', b'B*', b'b', b'b*'):
                rules.extend(path)
            path.clear()
            point = None
        elif operator in (b'q', b'Q', b'h', b'c', b'v', b'y', b're'):
            point = None

    page.extract_text(visitor_operand_before=before)
    return rules


def verify_model_groups(section, runs, rules):
    """Bind complete TEI rows to drawn metrics and uniquely bounded model groups."""
    rows = section.get('tableRows') or []
    bounds = section.get('tableBounds')
    if not bounds or len(rows) < 3 or len(rows[0]) < 3:
        return None
    header = rows[0]
    if _compact(header[0]['text']).casefold() not in {'model', 'method'} or header[1]['text'].strip():
        return None
    if any(cell['rows'] != 1 for cell in header) or any(cell['cols'] != 1 for cell in header[:2]):
        return None
    metrics = [name for cell in header[2:] for name in cell['text'].split()]
    if (not 2 <= len(metrics) <= 8 or len(set(metrics)) != len(metrics)
            or len(metrics) != sum(cell['cols'] for cell in header[2:])):
        return None

    x, y, width, height = bounds
    inside = [run for run in runs if x - 2 <= run['x'] <= x + width + 2
              and y - 2 <= run['y'] <= y + height + 3]
    lines = [(line[0]['y'], _tokens(line)) for line in _line_groups(inside)]
    expected = [_compact(header[0]['text']), *map(_compact, metrics)]
    headers = [(baseline, tokens) for baseline, tokens in lines
               if [_compact(token['text']) for token in tokens] == expected]
    if len(headers) != 1:
        return None
    header_y, tokens = headers[0]
    model_x, *columns = [token['x'] for token in tokens]
    gaps = [b - a for a, b in zip(columns, columns[1:])]
    if min(gaps) < 9:
        return None
    edges = [columns[0] - gaps[0] / 2, *((a + b) / 2 for a, b in zip(columns, columns[1:])), x + width + 3]
    cuts = sorted({round(baseline, 2) for left, right, baseline in rules
                   if x - 10 <= left <= x + 1 and x + width - 1 <= right <= x + width + 10
                   and header_y < baseline <= y + height + 10})
    models = [(index, row[0]['text']) for index, row in enumerate(rows[1:], 2) if row[0]['text'].strip()]
    if (len(models) < 2 or len(cuts) != len(models) + 1 or cuts[0] - header_y > 18
            or abs(cuts[-1] - y - height) > 10 or len({_compact(name) for _, name in models}) != len(models)):
        return None

    physical = []
    for (model_index, model), start, end in zip(models, cuts[:-1], cuts[1:], strict=True):
        model_anchors = 0
        for baseline, tokens in lines:
            if not start < baseline < end or not tokens:
                continue
            if abs(tokens[0]['x'] - model_x) <= 5:
                matches = [n for n in range(1, len(tokens) + 1)
                           if _compact(''.join(token['text'] for token in tokens[:n])) == _compact(model)]
                if len(matches) != 1 or tokens[matches[0] - 1]['x'] >= edges[0]:
                    return None
                model_anchors += 1
                tokens = tokens[matches[0]:]
            if len(tokens) <= len(metrics):
                continue
            data = tokens[-len(metrics):]
            values = [_compact(token['text']) for token in data]
            if (not all(_NUMERIC_CELL.fullmatch(value) for value in values)
                    or not all(lo <= token['x'] < hi for token, lo, hi in zip(data, edges[:-1], edges[1:], strict=True))):
                continue
            config = ' '.join(token['text'] for token in tokens[:-len(metrics)])
            physical.append((model_index, model, config, values, _compact(config + ''.join(values))))
        if model_anchors != 1:
            return None

    parsed = [(_compact(''.join(cell['text'] for cell in row[1:])), number)
              for number, row in enumerate(rows[1:], 2)]
    parsed_count, physical_count = Counter(key for key, _ in parsed), Counter(row[-1] for row in physical)
    parsed_rows = {key: number for key, number in parsed if parsed_count[key] == 1}
    checked, group_rows = [], {}
    for model_index, model, config, values, key in physical:
        number = parsed_rows.get(key)
        if number is None or physical_count[key] != 1:
            continue
        if checked and number <= checked[-1][0]:
            return None
        printed_config = rows[number - 1][1]['text']
        if _compact(printed_config) == _compact(config):
            config = printed_config
        checked.append([number, f'{model} / {config}', values])
        group_rows.setdefault(model_index, []).append(number)
    if not checked or any(index not in group_rows or not min(group_rows[index]) <= index <= max(group_rows[index])
                          for index, _ in models):
        return None
    return {'groups': [['', metrics]], 'rows': checked}
