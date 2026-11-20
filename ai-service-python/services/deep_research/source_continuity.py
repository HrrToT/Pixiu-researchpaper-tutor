"""Bounded retrieval context with independent source identities."""
import re


def enabled(record):
    return type(record.get('sourceContinuityContractVersion')) is int and record['sourceContinuityContractVersion'] in (1,2)


def method_enabled(record):
    return type(record.get('sourceContinuityContractVersion')) is int and record['sourceContinuityContractVersion']==2


def _body(item):
    text = item.get('text', '')
    if not isinstance(text, str):
        return ''
    return re.split(r'\bContent:\s*', text, maxsplit=1)[-1].lstrip()


def illustrative_reference(item):
    """A leading figure/table reference may omit its previously named subject."""
    return bool(re.match(r'(?:(?:in|as\s+(?:(?:shown|illustrated)\s+)?in)\s+'
        r'(?:fig(?:ure)?s?\.?|tables?)\s*\d+\b|(?:如|在)?\s*[图表]\s*\d+)', _body(item), re.I))


def method_reference(item):
    return bool(re.match(r'(?:after\b|for each\s+(?:selected|chosen|retained)\b|'
        r'based on (?:the|this|these|above)\b|随后|然后|对于每个(?:选中|选定)|基于上述)',_body(item),re.I))


def needs_preceding_context(item, *, illustrative=False,procedural=False):
    return bool(re.match(r'(?:where\b|which\b|this\b|these\b|it\b|however\b|in contrast\b|'
        r'on the contrary\b|其中|式中|该式|然而|相比之下)', _body(item), re.I)) or (
        illustrative is True and illustrative_reference(item)) or (procedural is True and method_reference(item))


def include_preceding_context(indexed, candidates, owned_id, limit, *, illustrative=False):
    """Add at most one predecessor; never concatenate or relabel its text.

    Missing/ambiguous ownership, index version or section disables expansion.
    Preserve the best semantic hit and the hit requiring context within the
    caller's existing source limit. This selection does not approve relevance.
    """
    selected = list(indexed[:limit])
    if limit < 2:
        return selected
    anchors = sorted(selected, key=lambda row: not illustrative_reference(row)) if illustrative is True else selected
    for anchor in anchors:
        meta = anchor.get('metadata') or {}
        chunk, version, section = meta.get('chunk_index'), meta.get('index_version'), meta.get('section_title')
        if (not needs_preceding_context(anchor, illustrative=illustrative) or meta.get('id') != owned_id
                or anchor.get('pdfId') != owned_id or type(chunk) is not int or chunk < 1
                or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{16}', version)
                or not isinstance(section, str) or not section.strip()):
            continue
        if illustrative is True and anchor.get('sourceId') != f'{owned_id}-v{version}-chunk-{chunk}':
            continue  # New context cannot borrow a forged/cross-family ID.
        matches = [row for row in candidates if row.get('pdfId') == owned_id
                   and (row.get('metadata') or {}).get('id') == owned_id
                   and (row.get('metadata') or {}).get('index_version') == version
                   and type((row.get('metadata') or {}).get('chunk_index')) is int
                   and (row.get('metadata') or {}).get('chunk_index') == chunk - 1
                   and (row.get('metadata') or {}).get('section_title') == section]
        if len(matches) != 1:
            continue
        previous = matches[0]
        if illustrative is True and previous.get('sourceId') != f'{owned_id}-v{version}-chunk-{chunk - 1}':
            continue
        if not previous.get('sourceId') or previous['sourceId'] in {row.get('sourceId') for row in selected}:
            continue
        if len(selected) >= limit:
            removable = [i for i, row in enumerate(selected) if i != 0 and row is not anchor]
            if not removable:
                continue
            selected.pop(removable[-1])
        selected.insert(selected.index(anchor), {**previous, 'retrievalMode': 'indexed_preceding_context',
                                                'contextForSourceId': anchor.get('sourceId')})
        return selected
    return selected


def _exact_indexed(row,owner):
    if not isinstance(row,dict):return None
    meta=row.get('metadata') or {}
    if not isinstance(meta,dict):return None
    chunk,version,section=meta.get('chunk_index'),meta.get('index_version'),meta.get('section_title')
    # The legacy owned-index adapter has sourceType, not an accessLevel field.
    # Accept only that known path when the field is absent; an explicit access
    # restriction must never be promoted to full text by this selector.
    owned_index = 'accessLevel' not in row and row.get('sourceType') == 'current_paper'
    if (row.get('pdfId')!=owner or meta.get('id')!=owner
            or not (row.get('accessLevel') == 'fulltext' or owned_index)
            or type(chunk) is not int or chunk<0 or not isinstance(version,str)
            or not re.fullmatch(r'[0-9a-f]{16}',version) or not isinstance(section,str) or not section.strip()
            or row.get('sourceId')!=f'{owner}-v{version}-chunk-{chunk}'):
        return None
    location=row.get('location')
    if location is not None and (not isinstance(location,dict)
            or 'chunk' in location and (type(location['chunk']) is not int or location['chunk']!=chunk)
            or 'section' in location and location['section']!=section):
        return None
    return chunk,version,section


def include_method_context(indexed,candidates,owned_id,limit):
    """At most two predecessors, separate identities, within the original limit.

    Preserve the best hit, procedural anchor and existing context pairs. If the
    complete selected bundle cannot fit, keep the original selection. No text,
    source permission or scientific decision is synthesized here.
    """
    selected=list(indexed[:limit])
    if limit<2:return selected
    if any(not isinstance(r,dict) for r in selected):return selected
    ids=[r.get('sourceId') for r in selected]
    if any(not isinstance(s,str) or not s for s in ids) or len(ids)!=len(set(ids)):return selected
    pairs=set()
    for r in selected:
        parent=r.get('contextForSourceId')
        if isinstance(parent,str) and parent in ids:pairs.update((r['sourceId'],parent))
    for anchor in selected:
        if not method_reference(anchor) or not _exact_indexed(anchor,owned_id):continue
        current=anchor;chain=[]
        for _ in range(2):
            identity=_exact_indexed(current,owned_id)
            if not identity or identity[0]<1 or not needs_preceding_context(current,procedural=True):break
            chunk,version,section=identity
            matches=[r for r in candidates if _exact_indexed(r,owned_id)==(chunk-1,version,section)]
            if len(matches)!=1:break
            previous=matches[0];chain.append((previous,current['sourceId']));current=previous
        chain_ids={r['sourceId'] for r,_ in chain};new_ids=chain_ids-set(ids)
        if not new_ids:continue
        protected=pairs|{ids[0],anchor['sourceId']}|chain_ids
        removable=[i for i,r in enumerate(selected) if r['sourceId'] not in protected]
        needed=max(0,len(selected)+len(new_ids)-limit)
        if len(removable)<needed:continue
        dropped=set(removable[-needed:]) if needed else set()
        original={r['sourceId']:r for r in selected}
        kept=[r for i,r in enumerate(selected) if i not in dropped and r['sourceId'] not in chain_ids]
        bundle=[original.get(r['sourceId'],{**r,'retrievalMode':'indexed_method_preceding_context',
            'contextForSourceId':parent}) for r,parent in reversed(chain)]
        position=next(i for i,r in enumerate(kept) if r['sourceId']==anchor['sourceId'])
        return kept[:position]+bundle+kept[position:]
    return selected
