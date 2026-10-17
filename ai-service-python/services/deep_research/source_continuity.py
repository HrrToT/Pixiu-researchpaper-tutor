"""Bounded retrieval context with independent source identities."""
import re


def needs_preceding_context(item):
    text = item.get('text', '')
    if not isinstance(text, str):
        return False
    body = re.split(r'\bContent:\s*', text, maxsplit=1)[-1].lstrip()
    return bool(re.match(r'(?:where\b|which\b|this\b|these\b|it\b|however\b|in contrast\b|'
                         r'on the contrary\b|其中|式中|该式|然而|相比之下)', body, re.I))


def include_preceding_context(indexed, candidates, owned_id, limit):
    """Add at most one predecessor; never concatenate or relabel its text.

    Missing/ambiguous ownership, index version or section disables expansion.
    Preserve the best semantic hit and the hit requiring context within the
    caller's existing source limit. This selection does not approve relevance.
    """
    selected = list(indexed[:limit])
    if limit < 2:
        return selected
    for anchor in selected:
        meta = anchor.get('metadata') or {}
        chunk, version, section = meta.get('chunk_index'), meta.get('index_version'), meta.get('section_title')
        if (not needs_preceding_context(anchor) or meta.get('id') != owned_id
                or anchor.get('pdfId') != owned_id or type(chunk) is not int or chunk < 1
                or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{16}', version)
                or not isinstance(section, str) or not section.strip()):
            continue
        matches = [row for row in candidates if row.get('pdfId') == owned_id
                   and (row.get('metadata') or {}).get('id') == owned_id
                   and (row.get('metadata') or {}).get('index_version') == version
                   and type((row.get('metadata') or {}).get('chunk_index')) is int
                   and (row.get('metadata') or {}).get('chunk_index') == chunk - 1
                   and (row.get('metadata') or {}).get('section_title') == section]
        if len(matches) != 1:
            continue
        previous = matches[0]
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
