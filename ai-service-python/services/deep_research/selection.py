"""Bound prompt size while retaining different papers and research obligations."""
from collections import deque
import json


def surrounding_context(evidence, window=240):
    """Exact, bounded adjacent text; the quote is already a separate field."""
    original, quote = evidence.get('sourceContext', ''), evidence.get('quote', '')
    offset = original.find(quote) if original and quote else -1
    if offset < 0:
        return {}
    end = offset + len(quote)
    return {'before': original[max(0, offset - window):offset],
            'after': original[end:end + window],
            'truncated': offset > window or len(original) > end + window}


def bounded_evidence_rows(rows, max_bytes=14000):
    """Select complete rows in the caller's balanced order; never clip a quote."""
    selected = []
    for row in rows:
        candidate = [*selected, row]
        if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) <= max_bytes:
            selected.append(row)
    return selected


def balanced_sample(items, key, limit):
    groups = {}
    for item in items:
        groups.setdefault(key(item), deque()).append(item)
    selected = []
    while groups and len(selected) < limit:
        for group in list(groups):
            selected.append(groups[group].popleft())
            if not groups[group]:
                del groups[group]
            if len(selected) == limit:
                break
    return selected
