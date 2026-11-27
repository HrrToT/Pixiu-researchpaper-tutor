"""Keep explicit table references tied to their source revision and printed label."""
from collections import Counter, defaultdict
import re


_TABLE = r'(?:\btable\s*|表\s*)(\d{1,3}[a-z]?)(?![0-9a-z])'
_REQUEST = re.compile(_TABLE, re.I)
_LIST = re.compile(_TABLE + r'\s*(?:[、,，/–-]|\band\b|及|和|与|至|到)\s*\d', re.I)
_CAPTION = re.compile(r'^\s*(?:table caption:\s*)?' + _TABLE + r'[ \t]*[:：.]', re.I | re.M)
_SECTION = re.compile(r'^\s*' + _TABLE + r'[ \t]*[:：.]?[ \t]*$', re.I)
_SIZED_MODEL = re.compile(r'^([A-Za-z][\w.-]*?)[\s\-‐‑–−]+(\d+(?:\.\d+)?[BM])$', re.I)
_MODEL_LIST = re.compile(r'^\s*(?:(?:和|与|及|、|,|，|\band\b|\bor\b)\s*\d+(?:\.\d+)?[BM](?![A-Za-z0-9])\s*)+', re.I)
_SAME_PAGE_PROSE = re.compile(r'同页(?:的)?(?:正文|文字|文中|叙述)|same[- ]page (?:prose|text)|(?:prose|text) on the same page', re.I)
_NUMERIC_CHANGE = re.compile(r'(?:\b(?:drop|decreas|increas|reduc|improv|chang|differ)\w*\b|下降|降低|减少|提高|差异)'
                             r'[^。；;]{0,80}\d|\d[^。；;]{0,80}(?:\b(?:percent(?:age)?|points)\b|%)', re.I)
_RATE = r'(?:准确率|成功率|错误率|比例|\b(?:accuracy|precision|recall|success rate|error rate)\b)'
_RATE_VALUE = r'(?<![\d.])(\d+(?:\.\d+)?)\s*(百分(?:比|点)|[%％]|percentage points?|percent)'
_RATE_CHANGE = re.compile(_RATE + r'[^。；;]{0,48}?' + _RATE_VALUE, re.I)


def same_page_prose_requested(question):
    return bool(_SAME_PAGE_PROSE.search(question))


def same_page_rate_enabled(record):
    from services.deep_research.request_context import effective_question

    version = record.get('namedTableSamePageRateVersion')
    if type(version) is not int or version != 1 or (record.get('state') or {}).get('outputKind') != 'claim_verification':
        return False
    question = effective_question(record)
    return same_page_prose_requested(question) and bool(re.search(_RATE, question, re.I)) and requested_number(question) is not None


def _requested_models(models, question):
    from services.deep_research.requested_table_rows import match_priority

    named = {model for model in models if match_priority(model, question)}
    # Extend an explicit model-size list only within the same family, e.g.
    # "Llama-2 13B and 70B". A size elsewhere in the question cannot select it.
    families = {}
    for model in models:
        if match := _SIZED_MODEL.fullmatch(model):
            families.setdefault(match[1].casefold(), {})[match[2].casefold()] = model
    for family, candidates in families.items():
        parts = [re.findall(r'[a-z]+|\d+|[^a-z\d]+', token) for token in re.split(r'[\s\-‐‑–−]+', family)]
        prefix = r'[\s\-‐‑–−]+'.join(
            r'[\s\-‐‑–−]*'.join(map(re.escape, tokens)) for tokens in parts)
        for anchor in re.finditer(r'(?<![A-Za-z0-9])' + prefix +
                                  r'[\s\-‐‑–−]+(\d+(?:\.\d+)?[BM])(?![A-Za-z0-9])', question, re.I):
            sizes = {anchor[1].casefold()}
            tail = _MODEL_LIST.match(question[anchor.end():])
            if tail:
                sizes.update(item.casefold() for item in re.findall(r'\d+(?:\.\d+)?[BM]', tail[0], re.I))
            named.update(candidates[size] for size in sizes & candidates.keys())
    return named


def requested_row_numbers(packet, question, *, grouped_rows=False):
    numbers = {number for number, label, _ in packet['rows'] if label.strip() and re.search(
        r'(?<![A-Za-z0-9_.-])' + r'\s+'.join(map(re.escape, label.split())) + r'(?![A-Za-z0-9_.-])',
        question, re.I)}
    if grouped_rows:
        groups = {label.split(' / ', 1)[0] for _, label, _ in packet['rows'] if ' / ' in label}
        layers = getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,)))
        named = _requested_models(groups, '\n'.join(layers))
        numbers.update(number for number, label, _ in packet['rows']
                       if ' / ' in label and label.split(' / ', 1)[0] in named)
    return numbers


def include_indexed_rows(rows, candidates, record, owner, limit):
    """Use existing retrieval slots for explicitly named verified rows of one table."""
    from services.deep_research.request_context import effective_question
    from services.deep_research.source_continuity import _exact_indexed
    from services.deep_research.table_evidence import visible_table_packet

    if record.get('namedTableScopeVersion') != 2 or record.get('state', {}).get('outputKind') != 'claim_verification':
        return rows
    question = effective_question(record)
    number = requested_number(question)
    anchor = _exact_indexed(rows[0], owner) if rows and limit >= 2 else None
    if not number or not anchor:
        return rows
    pool = [row for row in candidates if (identity := _exact_indexed(row, owner)) and identity[1] == anchor[1]]
    counts = Counter(row['sourceId'] for row in pool)
    matches = []
    for row in pool:
        location = row.get('location') or {}
        section = _SECTION.fullmatch(location.get('section', ''))
        table = location.get('table')
        if (counts[row['sourceId']] != 1 or not table or not section or section[1].casefold() != number):
            continue
        packet = visible_table_packet(row.get('tableData'), row.get('text', ''))
        matched = requested_row_numbers(packet, question,
            grouped_rows=record.get('namedTableGroupedRowsVersion') == 1) if packet else set()
        if matched:
            matches.append((row, matched))
    if not matches or len({row['location']['table'] for row, _ in matches}) != 1:
        return rows
    selected = list(rows[:limit])
    protected = {rows[0]['sourceId']}
    for row in selected:
        if row.get('contextForSourceId'):
            protected.update((row['sourceId'], row['contextForSourceId']))
    present = {row['sourceId'] for row in selected}
    covered = set()
    for row, numbers in matches:
        if row['sourceId'] in present:
            protected.add(row['sourceId'])
            covered.update(numbers)
    for row, numbers in sorted(matches, key=lambda item: (-len(item[1]), min(item[1]))):
        if numbers <= covered:
            continue
        if len(selected) >= limit:
            slot = next((i for i in reversed(range(len(selected))) if selected[i]['sourceId'] not in protected), None)
            if slot is None:
                break
            selected.pop(slot)
        selected.append(row)
        protected.add(row['sourceId'])
        covered.update(numbers)
    return selected


def requested_number(question):
    layers = getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,)))
    text = '\n'.join(layers)
    numbers = {label.casefold() for label in _REQUEST.findall(text)}
    return next(iter(numbers)) if len(numbers) == 1 and not _LIST.search(text) else None


def _identity(row):
    work, version = row.get('sourceWorkId'), row.get('sourceVersionId')
    if (work and version and row.get('ownerMaterialId') == work and row.get('accessLevel') == 'fulltext'
            and row.get('verification', {}).get('literal') == 'passed'):
        return work, version
    return None


def select(rows, number):
    """Exclude known other tables; keep unlabelled context without assigning it a table."""
    by_page, by_table = defaultdict(set), defaultdict(set)
    anchors = {}
    for row in rows:
        identity = _identity(row)
        if identity is None:
            continue
        loc = row.get('location') or {}
        page = loc.get('page') if loc.get('pageResolution') == 'exact' else None
        labels = set(_CAPTION.findall(row.get('quote', '')))
        section = _SECTION.match(loc.get('section', ''))
        if section:
            labels.add(section[1])
        labels = {label.casefold() for label in labels}
        table_key = (*identity, loc['table']) if loc.get('table') else None
        page_key = (*identity, page) if type(page) is int and page > 0 else None
        if table_key is not None:
            by_table[table_key].update(labels)
        if page_key is not None:
            by_page[page_key].update(labels)
        anchors[row['evidenceId']] = (labels, table_key, page_key)

    selected, matched = [], set()
    for row in rows:
        labels, table_key, page_key = anchors.get(row['evidenceId'], (set(), None, None))
        labels = labels | by_table.get(table_key, set())
        if labels and labels != {number}:
            continue
        selected.append(row)
        if labels == {number} or by_page.get(page_key) == {number}:
            matched.add(row['evidenceId'])
    return selected, matched


def preferred_read_rows(sources, question, limit, extracted, *, grouped_rows=False):
    """Read distinct requested rows for each eligible snapshot before generic passages."""
    from services.deep_research.table_evidence import visible_table_packet

    number = requested_number(question)
    if not number:
        return []
    per_source = defaultdict(list)
    for row in sources:
        loc = row.get('location') or {}
        section = _SECTION.fullmatch(loc.get('section', ''))
        if (not section or section[1].casefold() != number or not loc.get('table')
                or row['workId'] != row.get('ownerMaterialId') or row.get('accessLevel') != 'fulltext'
                or (row['sourceId'], row.get('contentHash')) in extracted):
            continue
        packet = visible_table_packet(row.get('tableData'), row.get('text', ''))
        matches = requested_row_numbers(packet, question, grouped_rows=grouped_rows) if packet else set()
        if matches:
            per_source[(row['workId'], row['versionId'])].append((row, matches))
    queues = []
    for candidates in per_source.values():
        if len({row['location']['table'] for row, _ in candidates}) != 1:
            continue
        kept, covered = [], set()
        for row, matches in sorted(candidates, key=lambda item: (-len(item[1]), min(item[1]))):
            if matches - covered:
                kept.append(row)
                covered.update(matches)
        queues.append(kept)
    return [queue[index] for index in range(max(map(len, queues), default=0))
            for queue in queues if index < len(queue)][:limit // 2]


def _same_page_prose(rows, table_rows, question):
    from services.deep_research.publication_identity import owned_evidence_publication

    pages = {(row['location'].get('page'), _identity(row)) for row in table_rows
             if row['location'].get('pageResolution') == 'exact'}
    revisions = {publication['revision'] for row in table_rows if (publication := owned_evidence_publication(row))}
    if len(pages) != 1 or len(revisions) != 1:
        return None
    page, owner = next(iter(pages))
    if type(page) is not int or page < 1:
        return None
    terms = re.findall(r'\b[A-Za-z][A-Za-z0-9.-]{1,}\b', question)
    rate_request = bool(re.search(_RATE, question, re.I))
    context = []
    for row in rows:
        location = row.get('location') or {}
        quote = row['quote']
        if (location.get('pageResolution') != 'exact' or location.get('page') != page or _identity(row) != owner
                or row.get('tableData') or location.get('table') or _CAPTION.search(quote)
                or (owned_evidence_publication(row) or {}).get('revision') not in revisions or not _NUMERIC_CHANGE.search(quote)):
            continue
        overlap = sum(bool(re.search(r'(?<![\w.-])' + re.escape(term) + r'(?![\w.-])', quote, re.I))
                      for term in set(terms))
        rate_value = rate_request and bool(_RATE_CHANGE.search(quote))
        context.append((rate_value, overlap, -len(quote), row))
    return max(context, key=lambda item: item[:3], default=(False, 0, 0, None))[3]


def prioritize(rows, bundles, matched, question, *, requested_rows=False, keep_revisions_together=False,
               grouped_rows=False, same_page_candidates=()):
    """Keep a caption and its available result passage together per revision."""
    revisions = defaultdict(list)
    for row in rows:
        if row['evidenceId'] in matched:
            revisions[_identity(row)].append(row)
    preferred = []
    companions = {}
    for identity, items in revisions.items():
        if requested_rows:
            from services.deep_research.table_evidence import visible_table_packet
            indexed = [(row, requested_row_numbers(packet, question, grouped_rows=grouped_rows)) for row in items
                       if (packet := visible_table_packet(row.get('tableData'), row['quote']))]
            indexed = [(row, matches) for row, matches in indexed if matches]
            if indexed and len({row['location'].get('table') for row, _ in indexed}) == 1:
                pair = []
                covered = set()
                for row, numbers in sorted(indexed, key=lambda item: (-len(item[1]), min(item[1]))):
                    if numbers - covered:
                        pair.append(row)
                        covered.update(numbers)
                obligations = next((row['obligationIds'] for row in pair if row.get('obligationIds')), [])
                if obligations:
                    if same_page_candidates and same_page_prose_requested(question):
                        if prose := _same_page_prose(same_page_candidates, pair, question):
                            pair.append(prose)
                            companions[prose['evidenceId']] = prose
                    preferred.append({'obligationId': obligations[0], 'criterionId': 'explicit_table_context',
                                      'requirement': question, 'source': identity[0],
                                      'evidenceIds': [row['evidenceId'] for row in pair]})
                    continue
        caption = next((row for row in items if _CAPTION.search(row['quote'])), None)
        passages = [row for row in items if row is not caption]
        result = max(passages, key=lambda row: len(re.findall(r'\d+\.\d+', row['quote'])), default=None)
        pair = [row for row in (caption, result) if row is not None]
        obligations = next((row['obligationIds'] for row in pair if row.get('obligationIds')), [])
        if obligations:
            preferred.append({'obligationId': obligations[0], 'criterionId': 'explicit_table_context',
                              'requirement': question, 'source': identity[0],
                              'evidenceIds': [row['evidenceId'] for row in pair]})
    if keep_revisions_together and len(preferred) > 1:
        combined = {**preferred[0], 'criterionId': 'explicit_table_context_across_versions',
                    'evidenceIds': list(dict.fromkeys(eid for bundle in preferred for eid in bundle['evidenceIds']))}
        preferred.insert(0, combined)
    known = {row['evidenceId'] for row in rows}
    ordered = sorted(rows, key=lambda row: row['evidenceId'] not in matched)
    ordered.extend(row for ref, row in companions.items() if ref not in known)
    return ordered, [*preferred, *bundles]


def same_page_rate_gaps(question, supplied, accepted):
    """A comparison still needs the actual rate stated in the accompanying prose."""
    from services.deep_research.publication_identity import owned_evidence_publication
    from services.deep_research.table_evidence import visible_table_packet

    number = requested_number(question)
    if number is None or not same_page_prose_requested(question) or not re.search(_RATE, question, re.I):
        return []
    selected, anchored = select(supplied, number)
    anchored = [row for row in selected if row['evidenceId'] in anchored
                and visible_table_packet(row.get('tableData'), row['quote'])]
    claims = [(set(claim.get('evidenceRefs', [])),
               {_rate_value(match) for match in re.finditer(_RATE_VALUE, claim['text'], re.I)})
              for claim in accepted if claim.get('kind') in {'reported', 'inference'}]
    gaps = []
    for identity in dict.fromkeys(_identity(row) for row in anchored):
        pair = [row for row in anchored if _identity(row) == identity]
        prose = _same_page_prose(selected, pair, question)
        rates = {_rate_value(match) for match in _RATE_CHANGE.finditer(prose['quote'])} if prose else set()
        if len(rates) != 1:
            continue
        rate, = rates
        if not any(prose['evidenceId'] in refs and rate in values for refs, values in claims):
            revision = owned_evidence_publication(prose)['revision']
            gaps.append({'question': f'核对 {revision} 表格与同页正文的数值',
                         'missingEvidence': f'正文中作者报告的{rate[1]}数值尚未在已核验答复中明确列出。'})
    return gaps


def _rate_value(match):
    from decimal import Decimal

    units = '百分点' if 'point' in match[2].casefold() or match[2] == '百分点' else '百分比'
    return Decimal(match[1]), units


GUIDANCE = ('For the explicitly requested numbered table, use only evidence whose location.requestedTable '
            'identifies that table as a candidate. A reference to the table in prose is not a row. '
            'Keep each paper revision separate and require the matching row, column and caption before interpreting '
            'a numerical value. Unlabelled rows cannot fill missing table cells. Do not infer that a paper omitted '
            'a configuration when the acquired row fragments are incomplete.')

SAME_PAGE_GUIDANCE = ('When comparing a table to accompanying prose, cite the table cells and the separate '
                      'same-page statement for the same revision. Explain any disagreement without choosing '
                      'which value is correct unless the source resolves it.')
SAME_PAGE_RATE_GUIDANCE = ('Same page means relative to the table within each revision. The PDF page numbers '
                           'can differ between revisions. Include the prose number and its unit in the answer.')
TABLE_SCOPE_CONDITIONS_GUIDANCE = ('Put source-stated experimental settings common to the compared rows '
                                   'in the reported claim conditions so formatting the bound rows retains them.')
