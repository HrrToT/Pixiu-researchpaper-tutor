"""Retrieve bounded literal successors of an explicitly requested section head."""
import hashlib
import re
from collections import Counter

from services.deep_research.source_continuity import _exact_indexed, _body


_PDF_HEADING = re.compile(r'(?m)^[ \t]*(?P<number>[1-9]\d?(?:\.\d{1,2}){0,3})\.?[ \t]+'
                          r'(?P<title>[A-Z][\w \t-]{2,90})[ \t]*$')
_HEADING_GLUE = {'a', 'an', 'and', 'for', 'in', 'of', 'on', 'the', 'to', 'with'}
_INLINE_METHOD_HEAD = re.compile(r'(?m)^\s*\d{1,2}\)[ \t]+([A-Za-z][A-Za-z -]{2,68}):[ \t]+')
_BACKGROUND_PATH = re.compile(r'\brelated works?\b', re.I)


def include_pdf_method_passages(rows, pages, record, query, material, limit):
    """Allocate two existing slots to literal passages from detected method sections."""
    from services.deep_research.audience_schedule import direct_reader_candidate
    from services.deep_research.external_sections import _NAV_OTHER, spans
    from services.deep_research.local_sources import _bm25, _tokens
    from services.deep_research.pdf_outline import normalized_title
    from services.deep_research.text_quality import control_count

    policy = record.get('localSectionContextContractVersion')
    if (policy not in (5, 6) or limit < 2
            or not direct_reader_candidate(record, record.get('state', {}).get('outputKind'))):
        return rows
    annotated = spans(pages, outline=True, normalize_headings=True, terminal_number_period=policy == 6)
    numbered_layout = policy == 6 and any(
        part['role'] == 'method' and re.match(r'^\d{1,2}\s+[^/]+ /', part['section'])
        for _, sections in annotated for part in sections)
    if policy == 6 and not numbered_layout:
        annotated = spans(pages, outline=True, normalize_headings=True)
    candidates = []
    title = material.get('title', '')
    short_title = re.match(r'^[A-Za-z0-9_-]+(?=\s*(?::|--|—))' if numbered_layout
                           else r'^[A-Za-z0-9_-]+(?=:)', title)
    ignored = {'paper', 'method', 'loss', 'training', 'using'}
    if short_title:
        ignored.add(short_title[0].casefold())
    tokens = _tokens(query)
    title_words = _tokens(title)
    if numbered_layout and title_words and tokens[:len(title_words)] == title_words:
        tokens = tokens[len(title_words):]
    terms = {word[:4] for word in tokens if word not in ignored}
    phrases = {(a[:4], b[:4]) for a,b in zip(tokens, tokens[1:]) if a not in ignored and b not in ignored}
    if not terms:
        return rows
    preceding_section, preceding_head = None, ''
    for page, sections in annotated:
        full_text = page['text']
        for section in sections:
            path = normalized_title(section['section'])
            if section['role'] != 'method' or _NAV_OTHER.search(path) or _BACKGROUND_PATH.search(path):
                preceding_section, preceding_head = None, ''
                continue
            start, end = section['start'], section['end']
            section_hits = len(terms & {word[:4] for word in _tokens(path) if word not in ignored})
            heads = list(_INLINE_METHOD_HEAD.finditer(full_text, start, end))
            head_by_offset = {h.start(): h[1] for h in heads}
            inherited = preceding_head if start == 0 and section['section'] == preceding_section else ''
            cuts = [start, *(h.start() for h in heads if h.start() > start), end]
            for left, right in zip(cuts, cuts[1:]):
                head = head_by_offset.get(left, inherited if left == start else '')
                heading_hits = len(terms & {word[:4] for word in _tokens(head) if word not in ignored})
                for offset in range(left, right, 1400):
                    text = full_text[offset:min(right, offset + 1800)]
                    if len(text.strip()) < 80 or control_count(text):
                        continue
                    words = [word[:4] for word in _tokens(text)]
                    hits = terms.intersection(words)
                    if hits:
                        loc = {'page': page['page'], 'offset': offset, 'section': section['section'],
                               'sectionRole': 'method', 'matchedPdfMethodPassage': True}
                        adjacent = len(phrases.intersection(zip(words, words[1:]))) if numbered_layout else 0
                        candidates.append((text, loc, hits, heading_hits, section_hits, adjacent))
            preceding_section, preceding_head = section['section'], heads[-1][1] if heads else inherited
    if not candidates:
        return rows
    scores = _bm25(query, [text for text, _, _, _, _, _ in candidates])
    ranked = sorted(zip(scores, candidates),
                    key=lambda pair: (pair[1][3], pair[1][5], pair[1][4], len(pair[1][2]), pair[0]), reverse=True)
    owner, content_hash = material['materialId'], material['contentHash']
    additions, locations_seen = [], set()
    for _, (text, location, _, _, _, _) in ranked:
        key = (location['page'], location['section']) if numbered_layout else location['page']
        if key in locations_seen:
            continue
        locations_seen.add(key)
        identity = hashlib.sha256(f'{owner}:{content_hash}:{location}'.encode()).hexdigest()
        additions.append({'sourceId': 'src_' + identity, 'pdfId': owner, 'text': text, 'location': location,
                          'contentHash': content_hash, 'versionId': material.get('versionId') or content_hash,
                          'title': material.get('title', owner), 'accessLevel': 'fulltext'})
        if len(additions) >= min(2, limit - 1):
            break
    if not additions:
        return rows
    pinned = {row.get('contextForSourceId') for row in rows}
    required = [row for row in rows if row.get('tableData') or row.get('contextForSourceId') or row['sourceId'] in pinned
                or row.get('location', {}).get('matchedPdfSubsection')]
    if len(required) >= limit:
        return rows
    preferred = [*required, *additions]
    used = {row['sourceId'] for row in preferred}
    return [*preferred, *(row for row in rows if row['sourceId'] not in used)][:limit]


def include_pdf_method_heading(rows, pages, record, query, material, limit):
    """Use one existing slot for an exact query-matched PDF subsection."""
    from services.deep_research.audience_schedule import direct_reader_candidate
    from services.deep_research.external_sections import _NAV_OTHER
    from services.deep_research.text_quality import control_count

    if (type(record.get('localSectionContextContractVersion')) is not int
            or record['localSectionContextContractVersion'] not in (4, 5, 6) or limit < 2
            or not direct_reader_candidate(record, record.get('state', {}).get('outputKind'))):
        return rows
    terms = set(re.findall(r'[a-z]+', query.casefold()))
    matches = []
    for page in pages:
        text = page['text']
        headings = list(_PDF_HEADING.finditer(text))
        for index, heading in enumerate(headings):
            title = heading['title'].strip()
            words = set(re.findall(r'[a-z]+', title.casefold())) - _HEADING_GLUE
            if '.' not in heading['number'] or not 2 <= len(words) <= 8 or not words <= terms or _NAV_OTHER.search(title):
                continue
            start = heading.start()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            passage = text[start:min(end, start + 1800)]
            if len(passage) - len(heading[0]) >= 80 and not control_count(passage):
                matches.append((page['page'], start, title, passage, len(words)))
    best = max((row[-1] for row in matches), default=0)
    strongest = [row for row in matches if row[-1] == best]
    if len(strongest) != 1:
        return rows
    page, offset, title, text, _ = strongest[0]
    location = {'page': page, 'offset': offset, 'section': title, 'sectionRole': 'method',
                'matchedPdfSubsection': True}
    owner, content_hash = material['materialId'], material['contentHash']
    identity = hashlib.sha256(f'{owner}:{content_hash}:{location}'.encode()).hexdigest()
    detail = {'sourceId': 'src_' + identity, 'pdfId': owner, 'text': text, 'location': location,
              'contentHash': content_hash, 'versionId': material.get('versionId') or content_hash,
              'title': material.get('title', owner), 'accessLevel': 'fulltext'}
    if any(row['sourceId'] == detail['sourceId'] for row in rows):
        return rows
    if len(rows) >= limit:
        pinned = {row.get('contextForSourceId') for row in rows}
        replace = next((index for index in reversed(range(1, len(rows)))
                        if not rows[index].get('tableData') and not rows[index].get('contextForSourceId')
                        and rows[index]['sourceId'] not in pinned), None)
        if replace is None:
            return rows
        rows = [row for index, row in enumerate(rows) if index != replace]
    return [*rows, detail]


def prioritize_pdf_heading(rows, ordered, bundles, record):
    """Keep a verified, contiguous subsection intact under the synthesis cap."""
    if type(record.get('localSectionContextContractVersion')) is not int or record['localSectionContextContractVersion'] not in (4, 5, 6):
        return ordered, bundles
    state = record['state']
    read = [source for source in state.get('readResults', [])
            if source.get('location', {}).get('matchedPdfSubsection') is True]
    if len(read) != 1:
        return ordered, bundles
    source, = read
    owner = source.get('ownerMaterialId')
    materials = record.get('materials', [])
    if (len(materials) != 1 or materials[0].get('materialId') != owner
            or source.get('workId') != owner or source.get('accessLevel') != 'fulltext'
            or materials[0].get('contentHash') != source.get('contentHash')
            or (materials[0].get('versionId') or materials[0].get('contentHash')) != source.get('versionId')):
        return ordered, bundles
    units = [row for row in rows if row.get('sourceId') == source['sourceId']
             and row.get('sourceWorkId') == owner and row.get('sourceVersionId') == source['versionId']
             and row.get('contentHash') == source['contentHash']
             and row.get('verification', {}).get('literal') == 'passed']
    units.sort(key=lambda row: row['location'].get('sourcePassageStart', -1))
    cursor = 0
    for unit in units:
        location = unit['location']
        end = cursor + len(unit['quote'])
        if location.get('sourcePassageStart') != cursor or location.get('sourcePassageEnd') != end:
            return ordered, bundles
        cursor = end
    if not 1 <= len(units) <= 8 or ''.join(row['quote'] for row in units) != source['text']:
        return ordered, bundles
    obligation_by_id = {o['obligationId']: o for item in state.get('plan', []) for o in item['obligations']}
    obligation = next((obligation_by_id[oid] for oid in source.get('obligationIds', [])
                       if oid in obligation_by_id and all(oid in row.get('obligationIds', []) for row in units)), None)
    if obligation is None:
        return ordered, bundles
    ids = {row['evidenceId'] for row in units}
    preferred = {'obligationId': obligation['obligationId'], 'criterionId': 'matched_pdf_subsection',
                 'requirement': obligation['question'], 'source': owner,
                 'evidenceIds': [row['evidenceId'] for row in units]}
    return [*units, *(row for row in ordered if row['evidenceId'] not in ids)][:20], [preferred, *bundles]


def prioritize_pdf_methods(rows, ordered, bundles, record):
    """Retain bounded exact excerpts from audited method reads in the draft input."""
    from services.deep_research.local_sources import _tokens
    from services.deep_research.selection import balanced_sample
    from services.deep_research.synthesis_evidence import readiness_bundles

    if record.get('localSectionContextContractVersion') not in (5, 6) or len(record.get('materials', ())) != 1:
        return ordered, bundles
    material, = record['materials']
    owner, content_hash = material.get('materialId'), material.get('contentHash')
    version = material.get('versionId') or content_hash
    if not all((owner, content_hash, version)):
        return ordered, bundles
    state = record['state']
    reads = {s['sourceId']:s for s in state.get('readResults', [])
             if s.get('location', {}).get('matchedPdfMethodPassage') is True
             and s.get('ownerMaterialId') == s.get('workId') == owner and s.get('versionId') == version
             and s.get('contentHash') == content_hash and s.get('accessLevel') == 'fulltext'}
    candidates = []
    for row in rows:
        read = reads.get(row.get('sourceId'))
        if (read and row.get('verification', {}).get('literal') == 'passed'
                and row.get('sourceWorkId') == owner and row.get('sourceVersionId') == version
                and row.get('contentHash') == content_hash and row.get('accessLevel') == 'fulltext'
                and row.get('quote') and row['quote'] in read['text']):
            candidates.append(row)
    if not candidates:
        return ordered, bundles
    preferred, navigation, exact_navigation = [], [], []
    whole_passages = record.get('localSectionContextContractVersion') == 6
    for item in state.get('plan', []):
        for obligation in item['obligations']:
            oid = obligation['obligationId']
            if owner not in obligation.get('requiredSources', []):
                continue
            terms = {w[:4] for w in _tokens(obligation.get('searchQuery', ''))}
            owned = [e for e in candidates if oid in e.get('obligationIds', []) and oid in reads[e['sourceId']].get('obligationIds', [])]
            def relevance(row):
                return (len(terms & {w[:4] for w in _tokens(row['quote'])}), -len(row['quote']))
            ranked = sorted(owned, key=relevance, reverse=True)
            for order, row in enumerate(balanced_sample(ranked, lambda e: e['sourceId'], 2)):
                if row not in preferred:
                    preferred.append(row)
                    navigation.append({'obligationId': oid, 'criterionId': 'pdf_method_passage',
                        'requirement': obligation['question'], 'source': owner, 'evidenceIds': [row['evidenceId']]})
                if whole_passages:
                    source_text = reads[row['sourceId']]['text']
                    units = sorted((part for part in owned if part['sourceId'] == row['sourceId']),
                                   key=lambda part: part['location'].get('sourcePassageStart', -1))
                    if len(source_text) <= 1500 and ''.join(part['quote'] for part in units) == source_text:
                        exact_navigation.append((order, {'obligationId':oid,'criterionId':'pdf_method_section',
                            'requirement':obligation['question'],'source':owner,
                            'evidenceIds':[part['evidenceId'] for part in units]}))
    shared = Counter(tuple(bundle['evidenceIds']) for _, bundle in exact_navigation)
    exact = [bundle for _, bundle in sorted(exact_navigation,
             key=lambda pair:(pair[0], -shared[tuple(pair[1]['evidenceIds'])]))]
    for bundle in exact:
        for part in candidates:
            if part['evidenceId'] in bundle['evidenceIds'] and part not in preferred:
                preferred.append(part)
    ids = {row['evidenceId'] for row in preferred}
    obligations = {o['obligationId']:o for item in state.get('plan', []) for o in item['obligations']}
    reviewed = readiness_bundles(rows, obligations, state.get('coverage', []))
    required = [bundle for bundle in bundles if bundle in reviewed]
    optional = [bundle for bundle in bundles if bundle not in reviewed]
    return [*preferred, *(row for row in ordered if row['evidenceId'] not in ids)][:20], [*required, *exact, *navigation, *optional]


def include_section_context(rows, candidates, record, owner, limit):
    selected = list(rows[:limit])
    if type(record.get('localSectionContextContractVersion')) is not int or record['localSectionContextContractVersion'] not in (1, 2, 3, 4, 5, 6):
        return selected
    from services.deep_research.section_premises import requested, explanation_only
    from services.deep_research.request_context import effective_question
    if not explanation_only(record) or limit < 2:
        return selected
    sections = requested(effective_question(record))
    ids = [r.get('sourceId') for r in selected]
    if not all(isinstance(i, str) and i for i in ids) or len(set(ids)) != len(ids):
        return selected
    for anchor in selected:
        identity = _exact_indexed(anchor, owner)
        if not identity or not any(re.search(r'(?m)^\s*' + re.escape(s) + r'\s+(?=[A-Z\u4e00-\u9fff])', _body(anchor)) for s in sections):
            continue
        chunk, version, section = identity
        chain = []
        current = anchor
        for step in (1, 2):
            matches = [r for r in candidates if _exact_indexed(r, owner) == (chunk + step, version, section)]
            if len(matches) != 1:
                break
            following = matches[0]
            page = current.get('location', {}).get('page')
            next_page = following.get('location', {}).get('page')
            if type(page) is not int or type(next_page) is not int or not page <= next_page <= page + 1:
                break
            chain.append(following)
            current = following
        if not chain:
            continue
        chain_ids = {r['sourceId'] for r in chain}
        protected = {ids[0], anchor['sourceId']} | chain_ids
        # Preserve previously selected context pairs as one bundle.
        for row in selected:
            parent = row.get('contextForSourceId')
            if parent in ids:
                protected.update((parent, row['sourceId']))
        additions = chain_ids - set(ids)
        needed = max(0, len(selected) + len(additions) - limit)
        removable = [i for i, r in enumerate(selected) if r['sourceId'] not in protected]
        if len(removable) < needed:
            continue
        dropped = set(removable[-needed:]) if needed else set()
        kept = [r for i, r in enumerate(selected) if i not in dropped and r['sourceId'] not in chain_ids]
        originals = {r['sourceId']: r for r in selected}
        bundle = [originals.get(r['sourceId'], {**r, 'retrievalMode': 'indexed_section_successor',
                    'contextForSourceId': anchor['sourceId']}) for r in chain]
        at = next(i for i, r in enumerate(kept) if r['sourceId'] == anchor['sourceId']) + 1
        return kept[:at] + bundle + kept[at:]
    return selected


def include_explanation_method(rows, candidates, record, query, owner, limit):
    """Reserve one existing slot for query-relevant method text in the same index version."""
    from services.deep_research.criterion_sources import acquisition_questions
    from services.deep_research.external_sections import _NAV_METHOD, _NAV_OTHER
    from services.deep_research.method_navigation import priority, requested
    from services.deep_research.section_premises import explanation_only

    selected = list(rows[:limit])
    version = record.get('localSectionContextContractVersion')
    if (type(version) is not int or version not in (3, 4, 5, 6) or limit < 2 or not selected
            or record.get('sourcePolicy', {}).get('mode') != 'task_only'
            or len(record.get('materials', [])) != 1 or not explanation_only(record, require_section=False)):
        return selected
    anchor = _exact_indexed(selected[0], owner)
    requirements = [q for q in acquisition_questions(record, query, owner) if requested(q)]
    if not anchor or not requirements:
        return selected

    def rank(row):
        identity = _exact_indexed(row, owner)
        if not identity or identity[1] != anchor[1] or row.get('tableData'):
            return (0, 0)
        section = identity[2]
        role = (row.get('location') or {}).get('sectionRole') or row['metadata'].get('section_role')
        if _NAV_OTHER.search(section) or not (role == 'method' or _NAV_METHOD.search(section)):
            return (0, 0)
        view = {**row, 'quote': _body(row), 'sourceTitle': row.get('title', '')}
        return max(((score[3], score[1]) for q in requirements
                    if (score := priority(view, q, query))[3] >= 2), default=(0, 0))

    if any(rank(row)[0] for row in selected):
        return selected
    counts = Counter(row.get('sourceId') for row in candidates)
    viable = [row for row in candidates if counts[row.get('sourceId')] == 1 and rank(row)[0]]
    if not viable:
        return selected
    detail = max(viable, key=rank)
    protected = {selected[0]['sourceId']} | {row['contextForSourceId'] for row in selected if row.get('contextForSourceId')}
    if len(selected) >= limit:
        replacement = next((i for i in reversed(range(len(selected)))
                            if selected[i]['sourceId'] not in protected and not selected[i].get('contextForSourceId')
                            and not selected[i].get('tableData')), None)
        if replacement is None:
            return selected
        selected.pop(replacement)
    return [*selected, detail]
