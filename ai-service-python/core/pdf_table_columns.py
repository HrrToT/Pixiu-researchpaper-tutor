"""Cross-check table columns against independent PDF drawing operations.

Regular groups, one-level mixed groups and flat headers are supported. Ambiguous
hierarchies, rotated pages and unsupported font geometry remain unverified. The
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


def _mixed_header_groups(section,inside,metrics,names):
    """Verify one physical parent band, including nonrepeating tail columns.

    Only labels drawn inside each column span can own it. TEI must corroborate
    the label (or an unambiguous long clipped suffix); it cannot assign spans.
    Multi-level irregular headers remain unsupported rather than guessed.
    """
    header_y=metrics[0]['y'];cells=[]
    for row in section.get('tableRows',[]):
        cells.extend(c['text'] for c in row if c['text'].strip())
        if any(compact(n).casefold() in compact(' '.join(c['text'] for c in row)).casefold() for n in names):break
    def label(tokens):
        value=' '.join(t['text'] for t in tokens);key=compact(value).casefold()
        exact=[c for c in cells if compact(c).casefold()==key]
        if exact:return exact[0]
        clipped=[c for c in cells if len(compact(c))>=8 and
                 (key.startswith(compact(c).casefold()) or key.endswith(compact(c).casefold()))]
        return value if len(clipped)==1 else None
    first=next((i for i in range(1,len(names)) if names[i].casefold()==names[0].casefold()),None)
    prefix=0
    if first:
        while prefix+first<=len(names) and [n.casefold() for n in names[prefix:prefix+first]]==[n.casefold() for n in names[:first]]:
            prefix+=first
    groups=[];spans=[]
    for start in range(0,prefix,first or 1):spans.append((start,start+first,True))
    spans.extend((i,i+1,False) for i in range(prefix,len(names)))
    bands=[]
    right=metrics[-1]['x']+(metrics[-1]['x']-metrics[-2]['x'])/2
    for run in inside:
        if not 1<header_y-run['y']<50:continue
        for token in run.get('tokens') or [run]:
            if metrics[0]['x']-2<=token['x']<=right and re.search(r'[A-Za-z0-9]',token['text']):
                bands.append({**token,'y':run['y']})
    if bands and max(t['y'] for t in bands)-min(t['y'] for t in bands)>1:return None
    for start,end,repeated in spans:
        if repeated:
            selected=[t for t in bands if metrics[start]['x']<=t['x']<=metrics[end-1]['x']]
        else:
            left=(metrics[start-1]['x']+metrics[start]['x'])/2 if start else metrics[0]['x']-2
            bound=(metrics[end-1]['x']+metrics[end]['x'])/2 if end<len(metrics) else right
            selected=[t for t in bands if left<=t['x']<bound]
        parent=label(sorted(selected,key=lambda t:t['x'])) if selected else None
        if parent is None and (selected or repeated or any(names[start].casefold()==n.casefold() for n in names[:start])):return None
        if parent is None:parent=''  # No printed parent: never invent a dataset/group.
        if groups and groups[-1][0]==parent and not repeated:groups[-1][1].extend(names[start:end])
        else:groups.append([parent,list(names[start:end])])
    if prefix and len({g[0] for g in groups[:prefix//first]})!=prefix//first:return None
    return groups


def verify_table_columns(section, runs, *, mixed=False):
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
        if mixed and compact(run['text']).casefold()=='compressionratio':
            metrics.append({**run,'text':'Compression Ratio'})
            continue
        # A single PDF text operation may draw several separated headings.
        for token in run.get('tokens') or [run]:
            name = unicodedata.normalize('NFKC', token['text'])
            if re.fullmatch(r'FPS|Size|Mem|Train|PSNR|SSIM|LPIPS', name, re.I):
                metrics.append({**token, 'text': name, 'y': run['y']})
    if len(metrics) < (2 if mixed else 4) or max(run['y'] for run in metrics) - min(run['y'] for run in metrics) > 1:
        return None
    metrics.sort(key=lambda run: run['x'])
    # Repeating an identical metric sequence anchors groups, rather than
    # expanding TEI colspan values whose labels may be damaged.
    names = [run['text'] for run in metrics]
    repeat = next((i for i in range(1, len(names)) if names[i].lower() == names[0].lower()), None)
    regular=bool(repeat and not len(names)%repeat and all(names[i:i+repeat]==names[:repeat] for i in range(0,len(names),repeat)))
    if not regular and not mixed:return None
    header_y = metrics[0]['y']
    groups = _verified_header_groups(rows, inside, metrics, names, repeat) if regular else None
    if groups is None and mixed:groups=_mixed_header_groups(section,inside,metrics,names)
    if groups is None:
        return None
    pdf_rows = []
    for run in sorted(inside, key=lambda run: (run['y'], run['x'])):
        if not pdf_rows or abs(pdf_rows[-1]['y'] - run['y']) > 3:
            pdf_rows.append({'y': run['y'], 'runs': []})
        pdf_rows[-1]['runs'].append(run)
    column_x = [run['x'] for run in metrics]
    first_boundary = column_x[0]-2 if mixed else column_x[0]-(column_x[1]-column_x[0])/2
    literal_rows = [];literal_y=[];label_x=[]
    for row in pdf_rows:
        if row['y'] <= header_y + 3 or any(run.get('tokens') is None for run in row['runs']):
            continue
        cells = [[] for _ in range(len(names) + 1)]
        for token in sorted([token for run in row['runs'] for token in run['tokens']], key=lambda token: token['x']):
            column = 0 if token['x'] < first_boundary else 1 + min(range(len(column_x)), key=lambda i: abs(column_x[i] - token['x']))
            cells[column].append(token['text'])
        literal_rows.append([compact(''.join(cell)) for cell in cells])
        literal_y.append(row['y'])
        label_x.append([t['x'] for r in row['runs'] for t in r['tokens'] if t['x']<first_boundary])
    if mixed:
        # Attach only isolated label footnotes to the unique following numeric
        # baseline within its superscript offset. Never move numeric-column
        # marks, digits, or markers shared by two possible physical rows.
        for i,values in enumerate(literal_rows):
            if not re.fullmatch(r'[*†‡]+',values[0]) or any(values[1:]):continue
            following=[j for j,v in enumerate(literal_rows) if 0<literal_y[j]-literal_y[i]<=5
                       and v[0] and all(v[1:]) and label_x[j]]
            if len(following)!=1 or not label_x[i]:continue
            j=following[0]
            if min(label_x[i])>=max(label_x[j]):literal_rows[j][0]+=values[0]
            elif max(label_x[i])<=min(label_x[j]):literal_rows[j][0]=values[0]+literal_rows[j][0]
    checked = []
    for number, row in enumerate(rows[1:], 2):
        if not row or any(cell['rows'] != 1 for cell in row):
            continue
        values = [cell['text'] for cell in row]
        if mixed:
            # TEI may merge several cells or clip their separators. Recover
            # boundaries ONLY from independently drawn PDF columns, requiring
            # an exact complete-row match and a unique physical row. Never
            # publish the damaged TEI cell division or round/convert a value.
            matches=[v for v in literal_rows if all(v) and
                     compact(''.join(v))==compact(''.join(values))]
            if len(matches)==1:
                label=values[0] if compact(values[0])==matches[0][0] else matches[0][0]
                checked.append([number,label,matches[0][1:]])
            continue
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


def _physical_table_caption(section,runs, *, two_tier=False, row_groups=False):
    """Read a unique adjacent physical caption, never borrow a TEI number."""
    bounds=section.get('tableBounds')
    if not bounds:return None
    x,y,w,h=bounds;candidates=[]
    padding = 50 if two_tier or row_groups else 30
    max_above = 25 if two_tier else 160
    separator = r'[.:]' if two_tier or row_groups else r'\.'
    for run in runs:
        match=re.match(r'^\s*Table\s*(\d+)'+separator,run['text'],re.I)
        if match and x-padding<=run['x']<=x+w+padding and (0<=y-run['y']<=max_above or 0<=run['y']-(y+h)<=25):
            candidates.append((match.group(1),run['y']))
    if len(candidates)!=1:return None
    number,start=candidates[0];stop=y-2 if start<y else start+100
    selected=[r for r in runs if start<=r['y']<=stop and x-padding<=r['x']<=x+w+padding]
    lines=[]
    for run in sorted(selected,key=lambda r:(r['y'],r['x'])):
        if not lines or run['y']-lines[-1][0]['y']>4:lines.append([])
        lines[-1].append(run)
    kept=[];previous=None
    for line in lines:
        baseline=max(r['y'] for r in line)
        if previous is not None and baseline-previous>16:break
        tokens=[t for r in line for t in (r.get('tokens') or [r])]
        kept.append(' '.join(t['text'] for t in sorted(tokens,key=lambda t:t['x'])))
        previous=baseline
    if not kept or len(kept)>12:return None
    return {'number':number,'text':' '.join(kept)}


_INNER_CAPTION = re.compile(r'^\s*Table\s*(\d+)\s*[:.]', re.I)


def _split_fused_table(section, runs, rules, captions):
    """Separate independently framed sub-tables inside one overgrown TEI zone."""
    from collections import defaultdict
    from core.pdf_model_table import verify_fused_model_groups

    x, y, width, height = section['tableBounds']
    rows = section['tableRows']
    printed = [(match[1], run['y']) for run in runs if x - 12 <= run['x'] <= x + width + 12
               and y <= run['y'] <= y + height
               if (match := _INNER_CAPTION.match(run['text']))]
    if len({number for number, _ in printed}) != len(printed):
        return None
    by_number = dict(printed)
    if any(number not in by_number for _, number in captions):
        return None
    if [by_number[number] for _, number in captions] != sorted(by_number[number] for _, number in captions):
        return None

    raw_lines = section['content'].splitlines()
    if len(raw_lines) != len(rows) + 1:
        return None
    first, first_number = captions[0]
    original = {**section, 'content': '\n'.join(raw_lines[:first + 1]), 'tableRows': rows[:first],
                'tableBounds': [x, y, width, by_number[first_number] - y]}
    pieces = [original]
    for position, (caption_row, number) in enumerate(captions):
        raw_end = captions[position + 1][0] if position + 1 < len(captions) else len(rows)
        baseline = by_number[number]
        next_caption = min((other_y for _, other_y in printed if other_y > baseline), default=y + height)
        bands = defaultdict(set)
        for left, right, rule_y in rules:
            if (x - 12 <= left < right <= x + width + 12 and right - left >= width / 2
                    and baseline < rule_y < next_caption):
                bands[round(left, 1), round(right, 1)].add(round(rule_y, 2))
        candidates = [(ends, sorted(levels)) for ends, levels in bands.items()
                      if len(levels) >= 4 and 5 <= min(levels) - baseline <= 65]
        if len(candidates) != 1:
            return None
        (left, right), cuts = candidates[0]
        candidates_rows = [[cell for cell in row if cell['text'].strip()] for row in rows[caption_row + 1:raw_end]]
        headers = [i for i, row in enumerate(candidates_rows[:4]) if len(row) >= 3
                   and compact(row[0]['text']).casefold() in {'model', 'method'}
                   and compact(row[1]['text']).casefold() in {'method', 'configuration'}]
        if len(headers) != 1:
            return None
        start = headers[0]
        # One top rule, one header rule, then one terminating rule per model group.
        stop = start + len(cuts) - 1
        if stop > len(candidates_rows):
            return None
        fragment = {**section, 'tableRows': candidates_rows[start:stop],
                    'tableBounds': [left, cuts[0], right - left, cuts[-1] - cuts[0]]}
        verified = verify_fused_model_groups(fragment, runs, rules)
        caption = _physical_table_caption(fragment, runs, row_groups=True) if verified else None
        if not caption or caption['number'] != number:
            return None

        table_id = f"pdf-page-{section['pageIndex'] + 1}-table-{number}"
        lines = ['Table caption: ' + caption['text'],
                 'Table row 1: Model / Configuration | ' + ' | '.join(verified['groups'][0][1]),
                 *(f'Table row {index}: ' + ' | '.join([label, *values]) for index, label, values in verified['rows'])]
        pieces.append({**fragment, 'id': f'table-{table_id}', 'section': f'Table {number}', 'tableId': table_id,
                       'content': '\n'.join(lines), 'tablePrefix': '\n'.join(lines[:2]),
                       'tableVerifiedData': verified, 'tableColumnMappingVersion': 2,
                       'unverifiedTeiTableId': section.get('tableId', '')})
        # The canonical PDF body still carries surrounding non-table prose and figures.
    return pieces


def attach_verified_table_columns(sections, pdf_path):
    from PyPDF2 import PdfReader
    from core.pdf_benchmark_columns import verify_two_tier_columns
    from core.pdf_model_table import horizontal_rules, verify_model_groups
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return sections
    pages, page_rules, splits = {}, {}, {}
    for section_index, section in enumerate(sections):
        index = section.get('pageIndex')
        if section.get('evidenceKind') != 'table' or index is None or not 0 <= index < len(reader.pages):
            continue
        if reader.pages[index].get('/Rotate', 0) % 360:
            continue
        try:
            if index not in pages:
                pages[index] = drawing_runs(reader.pages[index])
            captions = [(i, match[1]) for i, row in enumerate(section.get('tableRows') or ())
                        if len(texts := [cell['text'] for cell in row if cell['text'].strip()]) == 1
                        and (match := _INNER_CAPTION.match(texts[0]))]
            if captions:
                if section.get('tableBounds'):
                    if index not in page_rules:
                        page_rules[index] = horizontal_rules(reader.pages[index])
                    split = _split_fused_table(section, pages[index], page_rules[index], captions)
                    if split:
                        splits[section_index] = split
                continue  # Never verify rows from a combined zone under one caption.
            legacy = verify_table_columns(section,pages[index])
            verified = legacy or verify_table_columns(section,pages[index],mixed=True)
            caption=_physical_table_caption(section,pages[index]) if verified else None
            if verified and legacy is None and caption is None:verified=None
            if not verified:
                two_tier=verify_two_tier_columns(section,pages[index])
                caption=_physical_table_caption(section,pages[index],two_tier=True) if two_tier else None
                if caption:
                    verified=two_tier
            if not verified:
                caption = _physical_table_caption(section, pages[index], row_groups=True)
                if caption:
                    if index not in page_rules:
                        page_rules[index] = horizontal_rules(reader.pages[index])
                    verified = verify_model_groups(section, pages[index], page_rules[index])
        except (KeyError, ValueError, TypeError, ImportError, AttributeError):
            verified = None
        if verified:
            rebuilt_rows = verified.pop('rebuiltRows', False)
            section['tableVerifiedData'] = verified
            section['tableColumnMappingVersion'] = 2
            # Keep normalized table text and the checked packet identical for
            # downstream exact-quote checks; untouched rows retain raw TEI text.
            lines = section.get('content', '').splitlines()
            if caption:
                section.setdefault('unverifiedTeiTableLabel',section.get('section',''))
                section.setdefault('unverifiedTeiTableId',section.get('tableId',''))
                section.setdefault('unverifiedTeiCaption',lines[0] if lines else '')
                section['section']='Table '+caption['number']
                section['tableId']=f"pdf-page-{index+1}-table-{caption['number']}"
                if lines:lines[0]='Table caption: '+caption['text']
                section['tablePrefix']='\n'.join(lines[:2])
            if rebuilt_rows:
                # Renumber from the recovered physical rows so no legacy TEI
                # row can conflict with an independently checked coordinate.
                section['content'] = '\n'.join([*lines[:2], *(f'Table row {n}: ' + ' | '.join([label, *cells])
                    for n, label, cells in verified['rows'])])
                continue
            replacements = {f'Table row {n}: ': ' | '.join([method, *values])
                            for n, method, values in verified['rows']}
            section['content'] = '\n'.join(next((prefix + value for prefix, value in replacements.items()
                                                if line.startswith(prefix)), line) for line in lines)
    if splits:
        sections = [piece for i, section in enumerate(sections) for piece in splits.get(i, [section])]
    return _attach_ruled_percentage_tables(sections, reader, pages, page_rules)


def _attach_ruled_percentage_tables(sections, reader, drawing_cache, rule_cache):
    from collections import Counter

    from core.pdf_benchmark_columns import ruled_percentage_tables
    from core.pdf_model_table import horizontal_rules

    results = list(sections)
    for index, page in enumerate(reader.pages):
        if page.get('/Rotate', 0) % 360:
            continue
        try:
            plain_text = page.extract_text() or ''
            if not re.search(r'(?:\d+(?:\.\d+)?%[ \t]+){3,}\d+(?:\.\d+)?%', plain_text):
                continue
            runs = drawing_cache[index] if index in drawing_cache else drawing_runs(page)
            rules = rule_cache[index] if index in rule_cache else horizontal_rules(page)
            tables = list(ruled_percentage_tables(runs, rules, plain_text))
        except (KeyError, ValueError, TypeError, ImportError, AttributeError, UnboundLocalError):
            continue  # Unsupported text extraction or geometry cannot verify this page.
        counts = Counter(caption['number'] for _, caption, _, _ in tables)
        for bounds, caption, groups, values in tables:
            number = caption['number']
            if counts[number] != 1:
                continue
            candidates = [i for i, section in enumerate(results) if section.get('pageIndex') == index
                          and section.get('evidenceKind') == 'table'
                          and re.match(r'^Table\s+' + number + r'\b', section.get('section', ''), re.I)]
            if len(candidates) > 1:
                continue
            old = results[candidates[0]] if candidates else None
            if old and (old.get('tableVerifiedData') or not old.get('tableBounds')
                        or abs(old['tableBounds'][1] - bounds[1]) > 18):
                continue
            table_id = f'pdf-page-{index + 1}-table-{number}'
            rows = [[i, row[0], row[1:]] for i, row in enumerate(values, 2)]
            header = ' | '.join(' / '.join(filter(None, (parent, item))) for parent, items in groups for item in items)
            lines = ['Table caption: ' + caption['text'], 'Table row 1: ' + header,
                     *(f'Table row {i}: ' + ' | '.join([label, *cells]) for i, label, cells in rows)]
            table = {'id': f'table-{table_id}', 'section': f'Table {number}', 'tableId': table_id,
                     'page': index + 1, 'pageIndex': index, 'evidenceKind': 'table', 'tableBounds': bounds,
                     'content': '\n'.join(lines), 'tablePrefix': '\n'.join(lines[:2]),
                     'tableVerifiedData': {'groups': groups, 'rows': rows}, 'tableColumnMappingVersion': 2}
            if old:
                table['unverifiedTeiTableId'] = old.get('tableId', '')
                results[candidates[0]] = table
            else:
                results.append(table)
    return results
