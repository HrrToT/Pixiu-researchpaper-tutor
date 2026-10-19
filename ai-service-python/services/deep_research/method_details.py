"""Retrieve concrete component operations without changing passage identities."""
import re
from collections import Counter

from services.deep_research.source_continuity import needs_preceding_context


def enabled(record):
    return (type(record.get('sourcePrecisionContractVersion')) is int
            and record['sourcePrecisionContractVersion'] in {1, 2, 3, 4, 5, 6})


def _body(row):
    return re.split(r'\bContent:\s*', row.get('text', ''), maxsplit=1)[-1]


def include_method_details(indexed, candidates, query, owned_id, limit, *, semantic_intent=False, operational_intent=False,
                           intent_override=None,preserve_targets=None):
    """Reserve up to two existing slots for an explicit operation and its context.

    Literal query/component matches and operational language select candidates,
    never certify their relevance or factual support. The best semantic hit and
    existing context pairs remain protected. Ambiguous ownership/version/chunk
    identities disable the relevant expansion rather than merging source text.
    """
    selected = list(indexed[:limit])
    if not selected or limit < 2:
        return selected
    from services.deep_research.method_intent import query_intent, operation_score
    intent = intent_override or (query_intent(query,operational=operational_intent is True) if semantic_intent is True else None)
    if not intent and not re.search(r'predict\w*|input\w*|output\w*|mechanism|encod\w*|anneal\w*|'
                     r'deform\w*|parameter\w*|预测|输入|输出|机制|编码|退火|形变', query, re.I):
        return selected
    anchor = selected[0]
    meta = anchor.get('metadata') or {}
    version = meta.get('index_version')
    if (anchor.get('pdfId') != owned_id or meta.get('id') != owned_id
            or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{16}', version)):
        return selected
    owned = [row for row in candidates if row.get('pdfId') == owned_id
             and (row.get('metadata') or {}).get('id') == owned_id
             and (row.get('metadata') or {}).get('index_version') == version
             and isinstance(row.get('sourceId'), str) and row['sourceId']
             and type((row.get('metadata') or {}).get('chunk_index')) is int]
    ids = Counter(row['sourceId'] for row in owned)
    chunks = Counter(row['metadata']['chunk_index'] for row in owned)
    owned = [row for row in owned if ids[row['sourceId']] == 1
             and chunks[row['metadata']['chunk_index']] == 1]
    # Remove paper headers before matching: a method name in every header is
    # not evidence that a paragraph describes this queried component.
    acronyms = set(re.findall(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9-]{1,11}(?![A-Za-z0-9])', query))
    terms = set(re.findall(r'[a-z]{4,}', query.lower())) - {
        'input', 'inputs', 'output', 'outputs', 'prediction', 'predict', 'previous', 'frame',
        'representation', 'mechanism', 'parameters', 'changes', 'what', 'which', 'with', 'from'}
    concrete = re.compile(r'\b(?:outputs?|predicts?|dimensions?|maps?|noise|anneal\w*|'
                          r'offsets?|translations?|rotations?|updates?)\b|输入|输出|预测|偏移|噪声|退火', re.I)
    ranked = []
    for row in owned:
        body = _body(row)
        exact = sum(bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])', body))
                    for term in acronyms)
        overlap = len(terms & set(re.findall(r'[a-z]{4,}', body.lower())))
        rank_body = body
        if intent and needs_preceding_context(row):
            dm = row['metadata']
            previous = [p for p in owned if p['metadata']['chunk_index'] == dm['chunk_index']-1
                        and p['metadata'].get('section_title') == dm.get('section_title')]
            if len(previous) == 1:
                # Context affects ranking only. Return separate original sources
                # with unchanged IDs and the existing exact-predecessor guards.
                rank_body = _body(previous[0])+'\n'+body
        intent_score = operation_score(rank_body, row['metadata'].get('section_title',''), intent,
                                      operational=operational_intent is True)
        if (acronyms and not exact) or (not acronyms and (not intent_score if intent else overlap < 2)):
            continue
        operations = len({m.group(0).lower() for m in concrete.finditer(body)})
        if not operations and not intent_score:
            continue
        ranked.append((exact, intent_score, operations, overlap, row))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4]['metadata']['chunk_index']))
    protected = {anchor.get('sourceId'),*(preserve_targets or ())}
    for row in selected:
        if row.get('contextForSourceId'):
            protected.update((row['sourceId'], row['contextForSourceId']))
    selected_ids = {row.get('sourceId') for row in selected}
    if ranked and ranked[0][4]['sourceId'] in selected_ids:
        if preserve_targets is not None:
            preserve_targets.add(ranked[0][4]['sourceId'])
        return selected
    for *_, detail in ranked:
        if detail['sourceId'] in selected_ids:
            continue
        additions = [{**detail, 'retrievalMode': 'indexed_method_detail'}]
        if needs_preceding_context(detail):
            dm = detail['metadata']
            section = dm.get('section_title')
            previous = [row for row in owned if row['metadata']['chunk_index'] == dm['chunk_index'] - 1
                        and isinstance(section, str) and section.strip()
                        and row['metadata'].get('section_title') == section]
            if len(previous) != 1:
                continue
            if previous[0]['sourceId'] not in selected_ids:
                additions.insert(0, {**previous[0], 'retrievalMode': 'indexed_preceding_context',
                                     'contextForSourceId': detail['sourceId']})
        removable = [i for i, row in enumerate(selected) if row.get('sourceId') not in protected]
        needed = max(0, len(selected) + len(additions) - limit)
        if needed > len(removable):
            continue
        for index in sorted(removable[-needed:] if needed else [], reverse=True):
            selected.pop(index)
        selected[1:1] = additions
        if preserve_targets is not None:
            preserve_targets.update(row['sourceId'] for row in additions)
        return selected
    return selected
