"""Retain literal named table rows with their own caption, without numeric approval."""
import re

_ROWS = re.compile(r'^Table row \d+:\s*([^|\r\n]+)\|[^\r\n]*', re.M)
_CAPTIONS = re.compile(r'^Table caption:', re.M)
_GENERIC = {'method', 'scene', 'dataset', 'unit', 'model', 'metric', 'ours', 'baseline'}


def _requested_name(name, question):
    return (2 <= len(name) <= 80 and name.lower() not in _GENERIC
            and re.search(r'[A-Za-z\u4e00-\u9fff]', name)
            and re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', question, re.I))


def requested_table_row_spans(text, question, *, max_items=2, max_chars=3000):
    if not isinstance(text, str) or not isinstance(question, str):
        return []
    captions = [match.start() for match in _CAPTIONS.finditer(text)]
    spans = []
    for row in _ROWS.finditer(text):
        name = row.group(1).strip()
        if not _requested_name(name, question):
            continue
        starts = [start for start in captions if start < row.start()]
        if not starts:
            continue
        span = text[starts[-1]:row.end()]
        if len(span) <= max_chars and span not in spans:
            spans.append(span)
        if len(spans) >= max_items:
            break
    return spans


def requested_table_row_labels(text, question):
    """Return literal matched labels for retrieval ranking, not identity folding."""
    return list(dict.fromkeys(row.group(1).strip()
        for span in requested_table_row_spans(text, question)
        for row in _ROWS.finditer(span) if _requested_name(row.group(1).strip(), question)))
