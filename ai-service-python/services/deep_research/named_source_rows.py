"""Reserve bounded retrieval slots for explicitly requested literal row labels."""
from services.deep_research.requested_table_rows import requested_table_row_labels


def include_requested_rows(indexed, candidates, question, owned_id, limit):
    """Keep source/owner/index identities; never approve a table's measurements.

    A semantic hit can overlook a rare requested scene/sample label. Matching
    its literal caption/row is complementary retrieval, not a fuzzy identity or
    availability verdict. Preserve context pairs; prefer the named target over
    an extra generic hit when all remaining slots are already needed for context.
    """
    selected = list(indexed[:limit])
    if not selected or limit < 2:
        return selected
    import re
    anchor = selected[0]
    metadata = anchor.get('metadata') or {}
    version = metadata.get('index_version')
    if (anchor.get('pdfId') != owned_id or metadata.get('id') != owned_id
            or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{16}', version)):
        return selected
    owned = [row for row in candidates if row.get('pdfId') == owned_id
             and (row.get('metadata') or {}).get('id') == owned_id
             and (row.get('metadata') or {}).get('index_version') == version
             and isinstance(row.get('sourceId'), str) and row['sourceId']]
    counts = {}
    for row in owned:
        counts[row['sourceId']] = counts.get(row['sourceId'], 0) + 1
    labels = {row['sourceId']: requested_table_row_labels(row.get('text', ''), question)
              for row in owned if counts[row['sourceId']] == 1}
    matches = [row for row in owned if labels.get(row['sourceId'])]
    requested = {label for values in labels.values() for label in values}
    frequencies = {label: sum(bool(re.search(r'(?<![A-Za-z0-9_])' + re.escape(label)
        + r'(?![A-Za-z0-9_])', row.get('text', ''), re.I)) for row in owned)
        for label in requested}
    # A paper/method name repeats in headers. A rare explicitly requested scene
    # or sample must not lose its only slot to another row naming that method.
    matches.sort(key=lambda row: min(frequencies[label] for label in labels[row['sourceId']]))
    context_ids = set()
    for row in selected:
        if row.get('contextForSourceId'):
            context_ids.update((row['sourceId'], row['contextForSourceId']))
    protected = {anchor['sourceId']} | context_ids
    for row in matches[:min(2, limit - 1)]:
        if row['sourceId'] in {item['sourceId'] for item in selected}:
            protected.add(row['sourceId'])
            continue
        if len(selected) >= limit:
            removable = [i for i, item in enumerate(selected) if item['sourceId'] not in protected]
            if not removable:
                # A named scene/sample is an explicit user target. With a
                # three-slot envelope, keep its row plus the complete context
                # pair instead of spending the third slot on a generic hit.
                removable = [i for i, item in enumerate(selected)
                             if item['sourceId'] == anchor['sourceId']
                             and item['sourceId'] not in context_ids]
                if not removable:
                    break
            selected.pop(removable[-1])
        selected.append({**row, 'retrievalMode': 'indexed_requested_row'})
        protected.add(row['sourceId'])
    return selected
