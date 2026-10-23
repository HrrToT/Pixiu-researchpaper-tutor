"""Bound prompt size while retaining different papers and research obligations."""
from collections import deque
import json
import re


def distinct_evidence_candidates(rows):
    """Avoid repeating identical provenance/content in a bounded draft prompt.

    Only the evidence ID may differ. Different versions, locations, conditions,
    obligations or contexts remain separate candidates. Records without an
    explicit work/version identity are never merged. Stored evidence is untouched.
    """
    selected, seen = [], set()
    for row in rows:
        if not row.get('sourceWorkId') or not row.get('sourceVersionId'):
            selected.append(row)
            continue
        signature = json.dumps({key: value for key, value in row.items() if key != 'evidenceId'},
                               sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if signature not in seen:
            selected.append(row)
            seen.add(signature)
    return selected


def comparison_evidence_order(evidence, paper_titles):
    """Prefer a paper's own verified results before background baselines.

    This is prompt selection only, never a relevance or truth verdict. Retain
    every candidate and use the existing paper/obligation balancing afterwards.
    """
    from services.deep_research.table_evidence import visible_table_packet
    def rank(item):
        packet = visible_table_packet(item.get('tableData'), item.get('quote', ''))
        if not packet:
            return 1
        title = paper_titles.get(item.get('sourceWorkId'), '') or item.get('sourceTitle', '')
        title_key = re.sub(r'[^a-z0-9]', '', title.casefold())
        for _, method, _ in packet['rows']:
            method_key = re.sub(r'[^a-z0-9]', '', method.casefold())
            if re.match(r'^ours(?:\b|_)', method, re.I) or (len(method_key) >= 4 and title_key.startswith(method_key)):
                return 0
        return 2
    return sorted(evidence, key=rank)


def proposal_evidence_order(evidence, question):
    """Keep explicit rare labels and method choices ahead of generic benchmarks.

    Ranking never changes evidence, permissions or semantic verdicts. Subsequent
    paper/obligation balancing still applies. It does not declare a label relevant.
    """
    terms = set(re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}', question.casefold()))
    terms -= {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'paper', 'why', 'how'}
    def matches(item):
        quote = item.get('quote', '').casefold()
        return {term for term in terms if re.search(r'(?<![a-z0-9_])' + re.escape(term)
            + r'(?![a-z0-9_])', quote)}
    matched = [matches(item) for item in evidence]
    counts = {term: sum(term in row for row in matched) for term in terms}
    rare = {term for term, count in counts.items() if 0 < count <= max(1, len(evidence) // 3)}
    def rank(pair):
        index, item = pair
        table = bool(item.get('tableData') or re.match(r'\s*Table caption:', item.get('quote', ''), re.I))
        method = not table and (bool(item.get('conditions')) or bool(re.search(
            r'\b(?:train|optimi|updat|initializ|sampl|parameter)\w*|训练|初始化|更新|采样', item.get('quote', ''), re.I)))
        return (bool(matched[index] & rare), method, not table, -index)
    return [item for _, item in sorted(enumerate(evidence), key=rank, reverse=True)]


def surrounding_context(evidence, window=240):
    """Keep bounded sentence context so contrast subjects survive extraction."""
    from services.deep_research.quote_context import quote_context
    return quote_context(evidence, window)


def bounded_evidence_rows(rows, max_bytes=14000):
    """Preserve complete quotes before spending remaining space on context.

    A long context must not silently displace another candidate's whole quote.
    Omitted context is explicit; downstream checks must not resolve an unknown
    subject by inventing the missing antecedent.
    """
    selected = []
    contexts = []
    for row in rows:
        context = row.get('sourceContext')
        compact = {**row, 'sourceContext': {}, 'contextOmitted': True} if context else dict(row)
        candidate = [*selected, compact]
        if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) <= max_bytes:
            selected.append(compact)
            contexts.append(context)
    for i, context in enumerate(contexts):
        if not context:
            continue
        expanded = {**selected[i], 'sourceContext': context}
        expanded.pop('contextOmitted', None)
        candidate = [*selected[:i], expanded, *selected[i + 1:]]
        if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) <= max_bytes:
            selected[i] = expanded
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
