"""Link a verified PDF table to its named protocol and cited metric definition."""
import hashlib
import re
import unicodedata

from services.deep_research.obligation_binding import eligible_obligation_ids

_MAX_LENGTH = 1500
_PROCEDURE = re.compile(r'\b(?:evaluation protocol|we (?:evaluat\w*|comput\w*|follow|match\w*|measur\w*|'
                        r'perform\w*|select\w*|use)|to estimate)\b', re.I)
_APPENDIX_REF = re.compile(r'\b(?:evaluation metrics?|metric definitions?)[^.!?]{0,80}\b(?:see|in)\s+Appendix\s+([A-Z])\b', re.I)
_RUN_IN_HEADING = re.compile(r'(?m)^[ \t]*[A-Z][A-Za-z-]*(?: [A-Za-z-]+){0,4}\.\s+(?=[A-Z])')


def _appendix_metric(annotated, table_page, table):
    refs = {match[1].upper() for match in _APPENDIX_REF.finditer(table_page['text'])}
    if len(refs) != 1:
        return None
    appendix, = refs
    appendix_name = re.compile(rf'^(?:Appendix\s+)?{appendix}[.:]?\s+.*\b(?:metrics?|metric definitions?)\b', re.I)
    matches = []
    for page, sections in annotated:
        if page['page'] <= table_page['page']:
            continue
        for section in sections:
            if not appendix_name.search(section['section']):
                continue
            body = page['text'][section['start']:section['end']]
            for label, columns in table['tableData']['groups']:
                epsilon = {unicodedata.normalize('NFKC', column).split('=', 1)[0].strip() for column in columns}
                if not label.strip() or len(epsilon) != 1 or not epsilon.issubset({'ε', 'τ'}):
                    continue
                symbol, = epsilon
                header = re.compile(rf'(?m)^[ \t]*{re.escape(label)}\.\s+(?=[A-Z])', re.I)
                for match in header.finditer(body):
                    successor = _RUN_IN_HEADING.search(body, match.end())
                    original = body[match.start():successor.start() if successor else len(body)].rstrip()
                    normalized = unicodedata.normalize('NFKC', original)
                    if (80 <= len(original) <= _MAX_LENGTH
                            and re.search(rf'\bthreshold\s*{re.escape(symbol)}\b', normalized, re.I)):
                        matches.append((page['page'], section['start'] + match.start(),
                                        f'{section["section"]} / {label}', original, label))
    return matches[0] if len(matches) == 1 else None


def include_protocol(rows, pages, material, benchmarks, limit, *, include_metric_definition=False):
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
    annotated = spans(pages, outline=True, normalize_headings=True, terminal_number_period=True)
    same_page = [(page, sections) for page, sections in annotated if page['page'] == table_loc['page']]
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
    protocol = _source(material, location, original)
    retained = _retain(rows, protocol, table['sourceId'], limit)
    if not include_metric_definition or protocol not in retained:
        return retained
    metric = _appendix_metric(annotated, same_page[0][0], table)
    if not metric:
        return retained
    page, start, heading, original, label = metric
    if control_count(original) or len(original.encode('utf8')) > 3000:
        return retained
    location = {'page': page, 'offset': start, 'section': heading, 'benchmarkProtocolFor': table['sourceId'],
                'benchmarkMetricDefinition': label}
    return _retain(retained, _source(material, location, original), protocol['sourceId'], limit)


def _source(material, location, text):
    owner, content_hash = material['materialId'], material['contentHash']
    identity = hashlib.sha256(f'{owner}:{content_hash}:{location}'.encode()).hexdigest()
    return {'sourceId': 'src_' + identity, 'pdfId': owner, 'text': text, 'location': location,
            'contentHash': content_hash, 'versionId': material.get('versionId') or content_hash,
            'title': material.get('title', owner), 'accessLevel': 'fulltext'}


def _retain(rows, addition, anchor, limit):
    protected = {rows[0]['sourceId'], anchor}
    for row in rows:
        if row.get('tableData') or row.get('location', {}).get('benchmarkProtocolFor'):
            protected.add(row['sourceId'])
        if context := row.get('contextForSourceId'):
            protected.update((row['sourceId'], context))
    others = [row for row in rows if row['sourceId'] != addition['sourceId']]
    if len(others) >= limit:
        replace = next((i for i in reversed(range(len(others))) if others[i]['sourceId'] not in protected), None)
        if replace is None:
            return rows
        others.pop(replace)
    after = next(i + 1 for i, row in enumerate(others) if row['sourceId'] == anchor)
    return [*others[:after], addition, *others[after:]]


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


def synthesis_metric_bundles(evidence, rows, aliases):
    """Offer the full group to the fitter without increasing its size limit."""
    known = {row['evidenceId']: row for row in evidence if row.get('verification', {}).get('literal') == 'passed'}
    visible = [(row['evidenceId'], known[aliases[row['evidenceId']]]) for row in rows
               if aliases.get(row['evidenceId']) in known]
    bundles = []
    for table_alias, table in visible:
        if not table.get('tableData') or table.get('location', {}).get('thresholdColumnsVerified') is not True:
            continue
        linked = [(alias, row) for alias, row in visible
                  if row.get('location', {}).get('benchmarkProtocolFor') == table['sourceId']
                  and all(row.get(key) == table.get(key)
                          for key in ('ownerMaterialId', 'sourceWorkId', 'sourceVersionId', 'contentHash'))]
        protocol = [alias for alias, row in linked if not row['location'].get('benchmarkMetricDefinition')]
        definitions = [alias for alias, row in linked if row['location'].get('benchmarkMetricDefinition')]
        if len(protocol) == len(definitions) == 1:
            bundles.append((table_alias, protocol[0], definitions[0]))
    return bundles
