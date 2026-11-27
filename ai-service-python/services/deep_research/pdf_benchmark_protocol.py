"""Link a verified PDF table to its same-page, named protocol subsection."""
import hashlib
import re

from services.deep_research.obligation_binding import eligible_obligation_ids

_MAX_LENGTH = 1500
_PROCEDURE = re.compile(r'\b(?:evaluation protocol|we (?:evaluat\w*|comput\w*|follow|match\w*|measur\w*|'
                        r'perform\w*|select\w*|use)|to estimate)\b', re.I)


def include_protocol(rows, pages, material, benchmarks, limit):
    from services.deep_research.external_sections import spans
    from services.deep_research.measurement_table_navigation import threshold_caption_matches
    from services.deep_research.text_quality import control_count

    if not benchmarks or limit < 2:
        return rows
    tables = [row for row in rows if threshold_caption_matches(row, benchmarks)]
    if len(tables) != 1:
        return rows
    table, = tables
    table_loc = table['location']
    number = re.fullmatch(r'Table (\d+)', table_loc.get('section', ''))
    if not number:
        return rows
    reference = re.compile(rf'\b(?:in|from|see|shown in|reported in)\s+Table\s+{number[1]}\b', re.I)
    same_page = [(page, sections) for page, sections in spans(
        pages, outline=True, normalize_headings=True, terminal_number_period=True)
        if page['page'] == table_loc['page']]
    candidates = []
    for page, sections in same_page:
        for section in sections:
            heading = section['section'].rsplit(' / ', 1)[-1]
            heading_terms = {term.casefold() for term in re.findall(r'[A-Za-z][A-Za-z0-9-]+', heading)}
            if not re.match(r'^\d+(?:\.\d+)+\s', heading) or not heading_terms.intersection(benchmarks):
                continue
            start, end = section['start'], section['end']
            original = page['text'][start:end]
            prose = ' '.join(original.split())
            if (not 80 <= len(original) <= _MAX_LENGTH or len(original.encode('utf8')) > 3000
                    or control_count(original) or not reference.search(prose)
                    or len(_PROCEDURE.findall(prose)) < 2):
                continue
            candidates.append((start, heading, original))
    if len(candidates) != 1:
        return rows
    start, heading, original = candidates[0]
    owner, content_hash = material['materialId'], material['contentHash']
    if not owner or not content_hash or table.get('contentHash') != content_hash or table.get('pdfId') != owner:
        return rows
    location = {'page': table_loc['page'], 'offset': start, 'section': heading,
                'benchmarkProtocolFor': table['sourceId']}
    identity = hashlib.sha256(f'{owner}:{content_hash}:{location}'.encode()).hexdigest()
    protocol = {'sourceId': 'src_' + identity, 'pdfId': owner, 'text': original, 'location': location,
                'contentHash': content_hash, 'versionId': material.get('versionId') or content_hash,
                'title': material.get('title', owner), 'accessLevel': 'fulltext'}
    protected = {rows[0]['sourceId'], table['sourceId']}
    for row in rows:
        if row.get('tableData'):
            protected.add(row['sourceId'])
        if context := row.get('contextForSourceId'):
            protected.update((row['sourceId'], context))
    others = [row for row in rows if row['sourceId'] != protocol['sourceId']]
    if len(others) >= limit:
        replace = next((i for i in reversed(range(len(others))) if others[i]['sourceId'] not in protected), None)
        if replace is None:
            return rows
        others.pop(replace)
    after = next(i + 1 for i, row in enumerate(others) if row['sourceId'] == table['sourceId'])
    return [*others[:after], protocol, *others[after:]]


def owned_protocol(source, location, body, materials):
    if (not location.get('benchmarkProtocolFor') or source.get('accessLevel') != 'fulltext'
            or source.get('tableData') or len(source.get('pages', ())) != 1
            or body != source.get('text') or not 80 <= len(body) <= _MAX_LENGTH
            or len(body.encode('utf8')) > 3000):
        return False
    owner = source.get('ownerMaterialId')
    return bool(owner) and any(owner == material.get('materialId') == source.get('workId')
               and bool(material.get('contentHash'))
               and source.get('contentHash') == material['contentHash']
               and source.get('versionId') == (material.get('versionId') or material['contentHash'])
               for material in materials)


def preferred_protocol_reads(rows, tables, obligations, extracted):
    return [row for table in tables for row in rows
            if row.get('location', {}).get('benchmarkProtocolFor') == table['sourceId']
            and row['workId'] == table['workId'] and row.get('versionId') == table.get('versionId')
            and row.get('contentHash') == table.get('contentHash')
            and (row['sourceId'], row.get('contentHash')) not in extracted
            and eligible_obligation_ids(row, obligations)]


def readiness_source_ids(sources, benchmarks, evidence_source_ids):
    from services.deep_research.measurement_table_navigation import threshold_caption_matches

    visible = [row for row in sources if row['sourceId'] in evidence_source_ids]
    tables = {row['sourceId']: row for row in visible if threshold_caption_matches(row, benchmarks)}
    pairs = set()
    for row in visible:
        table = tables.get(row.get('location', {}).get('benchmarkProtocolFor'))
        if table and all(row.get(key) == table.get(key)
                         for key in ('ownerMaterialId', 'workId', 'versionId', 'contentHash')):
            pairs.update((table['sourceId'], row['sourceId']))
    return pairs
