"""Bounded retrieval context with independent source identities."""
import re


def enabled(record):
    return type(record.get('sourceContinuityContractVersion')) is int and record['sourceContinuityContractVersion'] == 1


def _body(item):
    text = item.get('text', '')
    if not isinstance(text, str):
        return ''
    return re.split(r'\bContent:\s*', text, maxsplit=1)[-1].lstrip()


def illustrative_reference(item):
    """A leading figure/table reference may omit its previously named subject."""
    return bool(re.match(r'(?:(?:in|as\s+(?:(?:shown|illustrated)\s+)?in)\s+'
        r'(?:fig(?:ure)?s?\.?|tables?)\s*\d+\b|(?:如|在)?\s*[图表]\s*\d+)', _body(item), re.I))


def needs_preceding_context(item, *, illustrative=False):
    return bool(re.match(r'(?:where\b|which\b|this\b|these\b|it\b|however\b|in contrast\b|'
        r'on the contrary\b|其中|式中|该式|然而|相比之下)', _body(item), re.I)) or (
        illustrative is True and illustrative_reference(item))


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
