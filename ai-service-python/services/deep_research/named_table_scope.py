"""Keep explicit table references tied to their source revision and printed label."""
from collections import defaultdict
import re


_TABLE = r'(?:\btable\s*|表\s*)(\d{1,3}[a-z]?)(?![0-9a-z])'
_REQUEST = re.compile(_TABLE, re.I)
_LIST = re.compile(_TABLE + r'\s*(?:[、,，/–-]|\band\b|及|和|与|至|到)\s*\d', re.I)
_CAPTION = re.compile(r'^\s*(?:table caption:\s*)?' + _TABLE + r'[ \t]*[:：.]', re.I | re.M)
_SECTION = re.compile(r'^\s*' + _TABLE + r'[ \t]*[:：.]?[ \t]*$', re.I)


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


def prioritize(rows, bundles, matched, question):
    """Keep a caption and its available result passage together per revision."""
    revisions = defaultdict(list)
    for row in rows:
        if row['evidenceId'] in matched:
            revisions[_identity(row)].append(row)
    preferred = []
    for identity, items in revisions.items():
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
