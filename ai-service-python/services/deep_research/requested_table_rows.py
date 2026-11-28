"""Retain literal named table rows with their own caption, without numeric approval."""
import re

_ROWS = re.compile(r'^Table row \d+:\s*([^|\r\n]+)\|[^\r\n]*', re.M)
_CAPTIONS = re.compile(r'^Table caption:', re.M)
_GENERIC = {'method', 'scene', 'dataset', 'unit', 'model', 'metric', 'ours', 'baseline'}


def enabled(record):
    return type(record.get('namedRowIdentityContractVersion')) is int and record['namedRowIdentityContractVersion'] == 1


def human_row_question(record):
    from services.deep_research.request_context import effective_question
    question = effective_question(record)
    return '\n'.join(getattr(question, 'instruction_layers', (question,)))


def _literal_label(label, question, *, cosmetic=False):
    pattern = (r'[\s\-‐‑–]*'.join(re.escape(part) for part in re.split(r'[\s\-‐‑–]+', label))
               if cosmetic else re.escape(label))
    return bool(re.search(r'(?<![A-Za-z0-9_*+.-])' + pattern
        + r'(?![A-Za-z0-9_]|\s*[*+_-]|\s*\.[A-Za-z0-9_])', question, re.I))


def match_priority(name, question):
    """Search hints only: cosmetic spelling never approves source identity."""
    if not (2 <= len(name) <= 80 and re.search(r'[A-Za-z\u4e00-\u9fff]',name)):
        return 0
    label = re.sub(r'\s*\[\d+(?:\s*[,\-–]\s*\d+)*\]\s*$','',name).strip()
    if label.lower() in _GENERIC:
        return 0
    if _literal_label(name,question):return 3
    if _literal_label(label,question):return 2
    # Preserve stars, suffixes, splits and all source text. A direct literal
    # match ranks above this complementary whitespace/hyphen search alias.
    return 1 if _literal_label(label,question,cosmetic=True) else 0


def _requested_name(name, question, *, symbol_identity=False):
    if symbol_identity:
        return match_priority(name,question)>0
    return (2 <= len(name) <= 80 and name.lower() not in _GENERIC
            and re.search(r'[A-Za-z\u4e00-\u9fff]', name)
            and re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', question, re.I))


def requested_table_row_spans(text, question, *, max_items=2, max_chars=3000, symbol_identity=False):
    if not isinstance(text, str) or not isinstance(question, str):
        return []
    captions = [match.start() for match in _CAPTIONS.finditer(text)]
    spans = []
    rows=list(_ROWS.finditer(text))
    if symbol_identity:
        rows.sort(key=lambda row:(-match_priority(row.group(1).strip(),question),row.start()))
    for row in rows:
        name = row.group(1).strip()
        if not _requested_name(name, question,symbol_identity=symbol_identity):
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


def requested_table_row_labels(text, question, *, symbol_identity=False):
    """Return literal matched labels for retrieval ranking, not identity folding."""
    return list(dict.fromkeys(row.group(1).strip()
        for span in requested_table_row_spans(text, question,symbol_identity=symbol_identity)
        for row in _ROWS.finditer(span) if _requested_name(row.group(1).strip(),question,symbol_identity=symbol_identity)))
