"""Cross-check simple grouped table columns against PDF drawing operations.

This deliberately leaves irregular/rotated/multiline tables unverified. The
private PyPDF2 font adapter is isolated here; unsupported adapters fail closed.
"""
import re
import unicodedata


def compact(text):
    return re.sub(r'\s+', '', str(text)).replace('∗', '*')


def drawing_runs(page):
    from PyPDF2._cmap import build_char_map

    fonts = {name: build_char_map(name, 200, page)[2:5]
             for name in page['/Resources']['/Font']}
    current_font = [None]
    font_size, horizontal_scale, char_space, word_space = [0], [1], [0], [0]
    runs = []
    text_advance = [0.0]

    def decode(value):
        encoding, cmap, _ = fonts[current_font[0]]
        raw = value if isinstance(value, bytes) else value.original_bytes
        if isinstance(encoding, str):
            decoded = raw.decode(encoding)
        else:
            decoded = ''.join(encoding.get(code, chr(code)) for code in raw)
        return ''.join(cmap.get(char, char) for char in decoded)

    def before(operator, operands, cm, tm):
        # PyPDF2's visitor text matrix does not advance after Tj/TJ. Consecutive
        # text-show operations share a line origin, but PDF glyph placement
        # continues after the previous glyph, including its font/word spacing.
        if operator in (b'BT', b'Tm', b'Td', b'TD', b'T*', b"'", b'"'):
            text_advance[0] = 0.0
        if operator == b'Tf':
            current_font[0] = operands[0]
            font_size[0] = float(operands[1])
        elif operator == b'Tz':
            horizontal_scale[0] = float(operands[0]) / 100
        elif operator == b'Tc':
            char_space[0] = float(operands[0])
        elif operator == b'Tw':
            word_space[0] = float(operands[0])
        if operator not in (b'Tj', b'TJ') or current_font[0] not in fonts:
            return
        # Rotated/skewed writing and unknown encodings do not verify a grid.
        if cm[1] or cm[2] or tm[1] or tm[2]:
            return
        values = operands[0] if operator == b'TJ' else operands
        try:
            text = ''.join(decode(value) for value in values if isinstance(value, (str, bytes)))
        except (LookupError, UnicodeError, AttributeError):
            return
        if text.strip():
            x = tm[4] * cm[0] + cm[4] + (text_advance[0] or 0.0)
            y = float(page.mediabox.height) - (tm[5] * cm[3] + cm[5])
            tokens = []
            ft = fonts[current_font[0]][2]
            scale = tm[0] * cm[0] * horizontal_scale[0]
            cursor, token, token_x = x, '', x
            # Only simple byte fonts with explicit widths verify cell values.
            # Header labels can still be read, but unsupported values stay raw.
            supported = text_advance[0] is not None and '/Widths' in ft and '/FirstChar' in ft
            for value in values if supported else []:
                if isinstance(value, (int, float)):
                    gap = -float(value) / 1000 * font_size[0] * scale
                    if gap > font_size[0] * scale * .18 and token:
                        tokens.append({'text': token, 'x': token_x})
                        token = ''
                    cursor += gap
                    continue
                raw = value if isinstance(value, bytes) else value.original_bytes
                for code in raw:
                    try:
                        letter = decode(bytes([code]))
                        width = float(ft['/Widths'][code - int(ft['/FirstChar'])])
                        if not 0 <= code - int(ft['/FirstChar']) < len(ft['/Widths']):
                            raise IndexError()
                    except (LookupError, UnicodeError, IndexError):
                        supported = False
                        break
                    if letter.isspace():
                        if token:
                            tokens.append({'text': token, 'x': token_x})
                            token = ''
                    else:
                        if not token:
                            token_x = cursor
                        token += letter
                    cursor += (width / 1000 * font_size[0] + char_space[0]
                               + (word_space[0] if code == 32 else 0)) * scale
                if not supported:
                    break
            if token:
                tokens.append({'text': token, 'x': token_x})
            text_advance[0] = (cursor - (tm[4] * cm[0] + cm[4])) if supported else None
            runs.append({'text': text, 'x': x, 'y': y, 'tokens': tokens if supported else None})

    page.extract_text(visitor_operand_before=before)
    return runs


def _verified_header_groups(rows, inside, metrics, names, repeat):
    """Retain all geometry-confirmed levels of a regular grouped header.

    TEI colspans alone cannot assign a column. Each PDF header token must also
    occur in the TEI header, and every level must align to equal metric groups.
    Irregular or ambiguous hierarchies stay unverified.
    """
    header_y = metrics[0]['y']
    header_cells = []
    for row in rows:
        header_cells.extend(cell['text'] for cell in row if cell['text'].strip())
        joined = compact(' '.join(cell['text'] for cell in row)).casefold()
        if all(name.casefold() in joined for name in names[:repeat]):
            break
    candidates = []
    for run in inside:
        if not 1 < header_y - run['y'] < 50:
            continue
        tokens = run.get('tokens') or [run]
        # Keep multiword names drawn by one operation when all words occupy
        # the same metric group and TEI corroborates the full name.
        if (len(tokens) > 1 and any(compact(run['text']).casefold() in compact(cell).casefold()
                                   for cell in header_cells)
                and any(all(metrics[i]['x'] <= t['x'] <= metrics[i + repeat - 1]['x'] for t in tokens)
                        for i in range(0, len(metrics), repeat))):
            tokens = [run]
        for token in tokens:
            if (metrics[0]['x'] <= token['x'] <= metrics[-1]['x']
                    and re.search(r'[A-Za-z0-9]', token['text'])):
                candidates.append({**token, 'y': run['y']})
    bands = []
    for token in sorted(candidates, key=lambda t: (-t['y'], t['x'])):
        if not bands or abs(bands[-1][0]['y'] - token['y']) > 1:
            bands.append([])
        bands[-1].append(token)
    count = len(names) // repeat
    if not bands or len(bands[0]) != count:
        return None
    paths = [[] for _ in range(count)]
    previous_count = count + 1
    for band in bands:
        if len(band) > previous_count or count % len(band):
            return None
        width = count // len(band)
        for i, token in enumerate(sorted(band, key=lambda t: t['x'])):
            columns = metrics[i * width * repeat:(i + 1) * width * repeat]
            if not columns[0]['x'] <= token['x'] <= columns[-1]['x']:
                return None
            label = next((label for label in header_cells
                          if compact(token['text']).casefold() in compact(label).casefold()), None)
            if label is None:
                return None
            span = re.search(r'\s*'.join(re.escape(c) for c in compact(token['text'])), label, re.I)
            if span is None:
                return None
            for child in paths[i * width:(i + 1) * width]:
                child.insert(0, span.group().strip())
        previous_count = len(band)
    labels = [' / '.join(path) for path in paths]
    if len({compact(label).casefold() for label in labels}) != count:
        return None  # Repeated subheaders without a verified parent are ambiguous.
    return [[label, names[:repeat]] for label in labels]


def verify_table_columns(section, runs):
    """Return only headers AND complete rows corroborated by PDF geometry."""
    bounds = section.get('tableBounds')
    rows = section.get('tableRows') or []
    if not bounds or len(rows) < 2:
        return None
    x, y, width, height = bounds
    inside = [run for run in runs if x - 2 <= run['x'] <= x + width + 2
              and y - 2 <= run['y'] <= y + height + 2]
    metrics = []
    for run in inside:
        # A single PDF text operation may draw several separated headings.
        for token in run.get('tokens') or [run]:
            name = unicodedata.normalize('NFKC', token['text'])
            if re.fullmatch(r'FPS|Size|Mem|Train|PSNR|SSIM|LPIPS', name, re.I):
                metrics.append({**token, 'text': name, 'y': run['y']})
    if len(metrics) < 4 or max(run['y'] for run in metrics) - min(run['y'] for run in metrics) > 1:
        return None
    metrics.sort(key=lambda run: run['x'])
    # Repeating an identical metric sequence anchors groups, rather than
    # expanding TEI colspan values whose labels may be damaged.
    names = [run['text'] for run in metrics]
    repeat = next((i for i in range(1, len(names)) if names[i].lower() == names[0].lower()), None)
    if not repeat or len(names) % repeat or any(names[i:i + repeat] != names[:repeat]
                                               for i in range(0, len(names), repeat)):
        return None
    header_y = metrics[0]['y']
    groups = _verified_header_groups(rows, inside, metrics, names, repeat)
    if groups is None:
        return None
    pdf_rows = []
    for run in sorted(inside, key=lambda run: (run['y'], run['x'])):
        if not pdf_rows or abs(pdf_rows[-1]['y'] - run['y']) > 3:
            pdf_rows.append({'y': run['y'], 'runs': []})
        pdf_rows[-1]['runs'].append(run)
    column_x = [run['x'] for run in metrics]
    first_boundary = column_x[0] - (column_x[1] - column_x[0]) / 2
    literal_rows = []
    for row in pdf_rows:
        if row['y'] <= header_y + 3 or any(run.get('tokens') is None for run in row['runs']):
            continue
        cells = [[] for _ in range(len(names) + 1)]
        for token in sorted([token for run in row['runs'] for token in run['tokens']], key=lambda token: token['x']):
            column = 0 if token['x'] < first_boundary else 1 + min(range(len(column_x)), key=lambda i: abs(column_x[i] - token['x']))
            cells[column].append(token['text'])
        literal_rows.append([compact(''.join(cell)) for cell in cells])
    checked = []
    for number, row in enumerate(rows[1:], 2):
        if not row or any(cell['rows'] != 1 for cell in row):
            continue
        values = [cell['text'] for cell in row]
        if len(row) != len(names) + 1:
            # Recover only explicit whitespace-separated cells, then require
            # every recovered cell to match an independently drawn PDF column.
            values = [values[0], *(part for value in values[1:] for part in value.split())]
            if len(values) != len(names) + 1:
                continue
        elif any(cell['cols'] != 1 for cell in row):
            continue
        if [compact(value) for value in values] not in literal_rows:
            continue
        checked.append([number, values[0], values[1:]])
    return {'groups': groups, 'rows': checked} if checked else None


def attach_verified_table_columns(sections, pdf_path):
    from PyPDF2 import PdfReader
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return sections
    pages = {}
    for section in sections:
        index = section.get('pageIndex')
        if section.get('evidenceKind') != 'table' or index is None or not 0 <= index < len(reader.pages):
            continue
        if reader.pages[index].get('/Rotate', 0) % 360:
            continue
        try:
            if index not in pages:
                pages[index] = drawing_runs(reader.pages[index])
            verified = verify_table_columns(section, pages[index])
        except (KeyError, ValueError, TypeError, ImportError, AttributeError):
            verified = None
        if verified:
            section['tableVerifiedData'] = verified
            # Keep normalized table text and the checked packet identical for
            # downstream exact-quote checks; untouched rows retain raw TEI text.
            lines = section.get('content', '').splitlines()
            replacements = {f'Table row {n}: ': ' | '.join([method, *values])
                            for n, method, values in verified['rows']}
            section['content'] = '\n'.join(next((prefix + value for prefix, value in replacements.items()
                                                if line.startswith(prefix)), line) for line in lines)
    return sections
