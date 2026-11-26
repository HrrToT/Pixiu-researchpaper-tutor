"""Recover strictly framed metric tables when only original PDF text is available."""

from collections import defaultdict
import re

from core.pdf_table_columns import _physical_table_caption, compact, drawing_runs, verify_table_columns


_METRICS = re.compile(r'(?:FPS|Size|Mem|Train|PSNR|SSIM|LPIPS)\s*[↑↓]', re.I)
_CAPTION = re.compile(r'^Table\s*(\d+)\s*[:.]', re.I)


def verified_metric_tables(page, text):
    """Use text for candidate rows, and PDF coordinates to establish columns."""
    if page.get('/Rotate', 0) % 360:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = []
    for index, header in enumerate(lines):
        marked = _METRICS.findall(header)
        metrics = tuple(name.rstrip('↑↓ ').casefold() for name in marked)
        if (not 4 <= len(metrics) <= 24 or len(set(metrics)) * 2 > len(metrics)
                or _METRICS.sub('', header).strip()):
            continue
        for tail in range(index + 3, min(index + 34, len(lines))):
            caption = _CAPTION.match(lines[tail])
            if caption:
                candidates.append((caption[1], lines[tail], metrics, tuple(name[-1] for name in marked),
                                   lines[max(0, index - 2):index + 1], lines[index + 1:tail]))
                break
    if not candidates or len(candidates) > 4:
        return []

    from core.pdf_benchmark_columns import _line_groups
    from core.pdf_model_table import horizontal_rules

    runs = drawing_runs(page)
    rules = [(left, right, y) for left, right, y in horizontal_rules(page) if right - left > 60]
    captions = defaultdict(list)
    for run in runs:
        match = _CAPTION.match(run['text'].strip())
        if match:
            captions[match[1]].append(run['y'])
    headers = defaultdict(list)
    for line in _line_groups(runs):
        names = tuple(token['text'].casefold() for run in sorted(line, key=lambda item: item['x'])
                      for token in run.get('tokens') or () if token['text'].casefold() in
                      {'fps', 'size', 'mem', 'train', 'psnr', 'ssim', 'lpips'})
        if names:
            headers[names].append(line[0]['y'])

    tables = []
    for number, caption_line, metrics, directions, heading, plain_rows in candidates:
        if len(captions[number]) != 1 or len(headers[metrics]) != 1:
            continue
        header_y, = headers[metrics]
        caption_y, = captions[number]
        if caption_y <= header_y:
            continue
        stops = [rule for rule in rules if header_y < rule[2] < caption_y and caption_y - rule[2] <= 24]
        if not stops:
            continue
        left, right, bottom = max(stops, key=lambda rule: rule[2])
        starts = [y for x1, x2, y in rules if abs(x1 - left) <= 2 and abs(x2 - right) <= 2
                  and 5 <= header_y - y <= 36]
        if not starts:
            continue
        top = min(starts)
        section = {'tableBounds': [left, top, right - left, bottom - top],
                   'tableRows': [[{'text': value, 'rows': 1, 'cols': 1}]
                                 for value in (' '.join(heading), *plain_rows)]}
        packet = verify_table_columns(section, runs, mixed=True)
        caption = _physical_table_caption(section, runs, row_groups=True)
        if (not packet or len(packet['rows']) < 2 or not caption or caption['number'] != number
                or not compact(caption['text']).startswith(compact(caption_line))):
            continue
        rows = []
        for n, label, values in packet['rows']:
            source_row = plain_rows[n - 2]
            original_label = re.match(r'\s*'.join(map(re.escape, compact(label))).replace(r'\*', r'[*∗]'),
                                      source_row)
            rows.append([n, original_label[0].strip() if original_label else label, values])
        packet['rows'] = rows
        table = {'number': number, 'caption': caption_line, 'tableData': packet}
        if tuple(metric.casefold() for _, group in packet['groups'] for metric in group) == metrics:
            table['metricDirections'] = directions
        tables.append(table)
    return tables
