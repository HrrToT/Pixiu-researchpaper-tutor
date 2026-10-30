"""Retrieve bounded literal successors of an explicitly requested section head."""
import re

from services.deep_research.source_continuity import _exact_indexed, _body


def include_section_context(rows, candidates, record, owner, limit):
    selected = list(rows[:limit])
    if type(record.get('localSectionContextContractVersion')) is not int or record['localSectionContextContractVersion'] != 1:
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
