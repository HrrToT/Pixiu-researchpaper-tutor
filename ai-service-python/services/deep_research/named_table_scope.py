"""Keep explicit table references tied to their source revision and printed label."""
from collections import Counter, defaultdict
import re


_TABLE = r'(?:\btable\s*|表\s*)(\d{1,3}[a-z]?)(?![0-9a-z])'
_REQUEST = re.compile(_TABLE, re.I)
_LIST = re.compile(_TABLE + r'\s*(?:[、,，/–-]|\band\b|及|和|与|至|到)\s*\d', re.I)
_CAPTION = re.compile(r'^\s*(?:table caption:\s*)?' + _TABLE + r'[ \t]*[:：.]', re.I | re.M)
_SECTION = re.compile(r'^\s*' + _TABLE + r'[ \t]*[:：.]?[ \t]*$', re.I)


def requested_row_numbers(packet, question):
    return {number for number, label, _ in packet['rows'] if label.strip() and re.search(
        r'(?<![A-Za-z0-9_.-])' + r'\s+'.join(map(re.escape, label.split())) + r'(?![A-Za-z0-9_.-])',
        question, re.I)}


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
        matched = requested_row_numbers(packet, question) if packet else set()
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


def preferred_read_rows(sources, question, limit, extracted):
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
        matches = requested_row_numbers(packet, question) if packet else set()
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


def prioritize(rows, bundles, matched, question, *, requested_rows=False):
    """Keep a caption and its available result passage together per revision."""
    revisions = defaultdict(list)
    for row in rows:
        if row['evidenceId'] in matched:
            revisions[_identity(row)].append(row)
    preferred = []
    for identity, items in revisions.items():
        if requested_rows:
            from services.deep_research.table_evidence import visible_table_packet
            indexed = [(row, requested_row_numbers(packet, question)) for row in items
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
    return sorted(rows, key=lambda row: row['evidenceId'] not in matched), [*preferred, *bundles]


GUIDANCE = ('For the explicitly requested numbered table, use only evidence whose location.requestedTable '
            'identifies that table as a candidate. A reference to the table in prose is not a row. '
            'Keep each paper revision separate and require the matching row, column and caption before interpreting '
            'a numerical value. Unlabelled rows cannot fill missing table cells. Do not infer that a paper omitted '
            'a configuration when the acquired row fragments are incomplete.')
