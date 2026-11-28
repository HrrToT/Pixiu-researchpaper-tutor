"""Rank literal benchmark groups from verified table packets."""
from collections import Counter
import re

from services.deep_research.source_continuity import _exact_indexed
from services.deep_research.table_evidence import visible_table_packet


_RESULT_REQUEST = re.compile(r'比较|核对|数值|报告|结果|指标|评估|表现|版本|性能|'
                             r'\b(?:compar\w*|check|results?|metrics?|performance|accuracy|report\w*|versions?)\b', re.I)
_GENERIC_GROUPS = {'all', 'average', 'overall', 'metric', 'metrics', 'results', 'benchmark', 'dataset', 'datasets'}


def enabled(record):
    version = record.get('namedBenchmarkNavigationVersion')
    return type(version) is int and version == 1


def human_text(record):
    from services.deep_research.request_context import effective_question

    question = effective_question(record)
    return '\n'.join(getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,))))


def _matching_packet(row, request, human):
    if not _RESULT_REQUEST.search(request):
        return None
    packet = visible_table_packet(row.get('tableData'), row.get('text', ''))
    if not packet:
        return None
    count = 0
    for group, _metrics in packet['groups']:
        words = group.strip().split()
        if not words or len(group.strip()) < 2 or group.casefold() in _GENERIC_GROUPS:
            continue
        pattern = r'(?<![a-zA-Z0-9_\-])' + r'\s+'.join(map(re.escape, words)) + r'(?![a-zA-Z0-9_\-])'
        if re.search(pattern, request, re.I) and re.search(pattern, human, re.I):
            count += 1
    return (count, packet) if count else None


def _ranked(rows, requests, human):
    ranked = []
    for row in rows:
        matched = [_matching_packet(row, request, human) for request in requests]
        best = max((result for result in matched if result), key=lambda value: value[0], default=None)
        if best:
            count, packet = best
            ranked.append((row, count, {entry[0] for entry in packet['rows']}))
    return sorted(ranked, key=lambda item: (item[1], len(item[2])), reverse=True)


def include_named_benchmark_tables(indexed, candidates, record, query, owner, limit):
    """Use at most two existing retrieval slots for the matching owned table."""
    from services.deep_research.criterion_sources import acquisition_questions

    selected = list(indexed[:limit])
    if not selected or limit < 2:
        return selected
    anchor = _exact_indexed(selected[0], owner)
    questions = acquisition_questions(record, query, owner)
    if not anchor or not questions:
        return selected
    human = human_text(record)
    pool = [row for row in candidates if (identity := _exact_indexed(row, owner)) and identity[1] == anchor[1]]
    counts = Counter(row['sourceId'] for row in pool)
    ranking = _ranked([row for row in pool if counts[row['sourceId']] == 1], [query, *questions], human)
    if not ranking:
        return selected
    matching_table = (ranking[0][0].get('location') or {}).get('table')
    if not matching_table:
        return selected
    protected = {selected[0]['sourceId']}
    for row in selected:
        if row.get('tableData'):
            protected.add(row['sourceId'])
        if row.get('contextForSourceId'):
            protected.update((row['sourceId'], row['contextForSourceId']))
    present = {row['sourceId'] for row in selected}
    covered_rows = set().union(*(numbers for row, _, numbers in ranking if row['sourceId'] in present
                                 and (row.get('location') or {}).get('table') == matching_table))
    admitted = 0
    for row, _count, numbers in ranking:
        if row['sourceId'] in present or (row.get('location') or {}).get('table') != matching_table or not numbers - covered_rows:
            continue
        if len(selected) >= limit:
            replace = next((i for i in reversed(range(len(selected))) if selected[i]['sourceId'] not in protected), None)
            if replace is None:
                break
            selected.pop(replace)
        selected.append(row)
        protected.add(row['sourceId'])
        covered_rows.update(numbers)
        admitted += 1
        if admitted == 2:
            break
    return selected


def preferred_benchmark_reads(sources, obligations, human, limit, extracted):
    """Prioritize one matching table from each eligible source revision."""
    from services.deep_research.obligation_binding import eligible_obligation_ids

    by_revision = {}
    for row in sources:
        work, version = row.get('workId'), row.get('versionId')
        table = (row.get('location') or {}).get('table')
        if (not work or not version or not table or row.get('ownerMaterialId') != work
                or row.get('accessLevel') != 'fulltext' or (row['sourceId'], row.get('contentHash')) in extracted):
            continue
        acquired_for = set(row.get('obligationIds') or ())
        eligible = [oid for oid in eligible_obligation_ids(row, obligations) if oid in acquired_for]
        requests = [value for oid in eligible for value in (obligations[oid].get('question', ''),
                                                            obligations[oid].get('searchQuery', ''))]
        ranked = _ranked([row], requests, human)
        if ranked:
            by_revision.setdefault((work, version), []).extend(ranked)
    queues = []
    for candidates in by_revision.values():
        candidates.sort(key=lambda item: (item[1], len(item[2])), reverse=True)
        table = candidates[0][0]['location']['table']
        kept = []
        covered = set()
        for row, _count, numbers in candidates:
            if row['location']['table'] == table and numbers - covered:
                kept.append(row)
                covered.update(numbers)
                if len(kept) == 2:
                    break
        queues.append(kept)
    return [queue[index] for index in range(2) for queue in queues if index < len(queue)][:limit // 2]
