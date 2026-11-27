"""Literal metric headers help locate tables; they never approve their values."""
import re

from services.deep_research.table_evidence import visible_table_packet

_DOMAINS = (
    ({'psnr', 'ssim', 'lpips', 'accuracy', 'f1', 'chamfer', 'cd'},
     r'quality|accuracy|precision|精度|画质|质量'),
    ({'fps', 'latency', 'rendertime'},
     r'\bfps\b|latency|rendering[- ]speed|render(?:ing)?[- ]time|帧率|渲染速度|渲染耗时'),
    ({'size', 'memory', 'mem', 'storage', 'modelsize', 'compressionratio'},
     r'storage|memory|model[- ]size|compression[- ]ratio|存储|内存|显存|压缩比'),
)
_GENERIC = {'the', 'a', 'an', 'each', 'both', 'all', 'this', 'these', 'their', 'our',
            'dataset', 'datasets', 'benchmark', 'benchmarks', 'results', 'result', 'quality',
            'performance', 'conditions', 'paper', 'papers', 'which', 'what', 'it', 'cpu', 'gpu'}
_RESULT = re.compile(r'定量|结果|指标|评测|数值|\b(?:quantitative|results?|metrics?|evaluation|accuracy|score)\b', re.I)
_NAME = re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9-]{3,}(?![A-Za-z0-9_-])')


def requested_threshold_benchmarks(question, query):
    if not _RESULT.search(query):
        return set()
    human = _NAME.findall(question)
    planned = _NAME.findall(query)
    names = {name.casefold() for name in (*human, *planned) if re.search(r'[A-Z0-9]', name[1:])}
    return (names & {word.casefold() for word in human} & {word.casefold() for word in planned}) - _GENERIC


def _threshold_match(source, benchmarks):
    if not benchmarks or (source.get('location') or {}).get('thresholdColumnsVerified') is not True:
        return 0
    caption = source.get('text', '').split('\n', 1)[0]
    heading = re.match(r'^Table caption:\s*Table\s*\d+\s*[:.]\s*(.+)', caption)
    if not heading:
        return 0
    words = {name.casefold() for name in _NAME.findall(heading[1].split('. ', 1)[0])}
    return len(words & benchmarks)


def retain_threshold_table(rows, candidates, benchmarks, limit):
    """Keep one physically verified table for an explicitly requested benchmark."""
    if not benchmarks or limit < 2:
        return rows
    matches = []
    for row in candidates:
        if score := _threshold_match(row, benchmarks):
            matches.append((score, row))
    if not matches:
        return rows
    best = max(score for score, _ in matches)
    winners = [row for score, row in matches if score == best]
    if len(winners) != 1 or any(row['sourceId'] == winners[0]['sourceId'] for row in rows):
        return rows
    table, = winners
    protected = {rows[0]['sourceId']} if rows else set()
    for row in rows:
        if row.get('tableData'):
            protected.add(row['sourceId'])
        if context := row.get('contextForSourceId'):
            protected.update((row['sourceId'], context))
    if len(rows) < limit:
        return [*rows[:1], table, *rows[1:]]
    replace = next((i for i in reversed(range(len(rows))) if rows[i]['sourceId'] not in protected), None)
    if replace is None:
        return rows
    return [*rows[:1], table, *rows[1:replace], *rows[replace + 1:]]


def preferred_threshold_reads(sources, obligations, human, limit, extracted):
    from services.deep_research.obligation_binding import eligible_obligation_ids
    from services.deep_research.selection import balanced_sample

    targets = {oid: requested_threshold_benchmarks(human, row.get('searchQuery') or row.get('question', ''))
               for oid, row in obligations.items()}
    rows = [source for source in sources
            if (source['sourceId'], source.get('contentHash')) not in extracted
            and any(_threshold_match(source, targets[oid]) for oid in eligible_obligation_ids(source, obligations))]
    return balanced_sample(rows, lambda source: (source['workId'], source.get('versionId')), limit // 4)


def _key(text):
    text = re.sub(r'\([^)]*\)|\[[^]]*\]', '', text)
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def benchmark_metric(label):
    """Recognize the same literal result headers used in table retrieval."""
    key = _key(label)
    return any(key in metrics for metrics, _ in _DOMAINS)


def planned_query_priority(query):
    """Rank frozen retrieval queries by the number of named measurement domains."""
    return sum(bool(re.search(pattern, query, re.I) or any(
        re.search(r'(?<![A-Za-z0-9])' + re.escape(metric) + r'(?![A-Za-z0-9])', query, re.I)
        for metric in metrics)) for metrics, pattern in _DOMAINS)


def _benchmark_hints(query):
    # Only literal name-like targets, not an inferred benchmark from the paper title.
    names = re.findall(r'\b(?:on|dataset|benchmark)\s+([A-Za-z][A-Za-z0-9&_\-]*)', query, re.I)
    names += re.findall(r'\b(?:Dataset|Benchmark)[-_][A-Za-z0-9_-]+', query, re.I)
    names += re.findall(r'([A-Za-z][A-Za-z0-9&_\-]*)(?:数据集|基准)', query)
    return {_key(name) for name in names if name.casefold() not in _GENERIC}


def row_priority(source, request):
    """Prefer an explicitly named row, then a visible author-labelled result.

    This only breaks ties between matching metric packets. 'Ours' is a literal
    table label, not permission to infer provenance, variants or comparability.
    """
    if score(source, request) <= 0:
        return 0
    from services.deep_research.reading_roles import _text
    packet = visible_table_packet(source.get('tableData'), _text(source))
    query = request.get('query', '').casefold()
    labels = [row[1] for row in packet['rows']]
    if any(len(label.strip()) >= 3 and label.casefold() in query for label in labels):
        return 2
    return int(any(re.match(r'^(?:ours|our method|proposed)(?:\b|[-_*])', label, re.I)
                   for label in labels))


def score(source, request):
    """Count requested metric columns with a visible numeric cell, under scope.

    A match only changes navigation. No units, main-result status, comparability,
    direction, source support or dataset membership is inferred here.
    """
    if request.get('role') not in ('result', 'resource') or source.get('accessLevel') != 'fulltext':
        return 0
    query = request.get('query', '')
    if not isinstance(query, str):
        return 0
    from services.deep_research.reading_roles import _text
    text = _text(source)
    packet = visible_table_packet(source.get('tableData'), text)
    if not packet:
        return 0
    labels = ' '.join([group for group, _ in packet['groups']] + [row[1] for row in packet['rows']])
    captions = ' '.join(line for line in text.splitlines()
                        if re.match(r'\s*Table\s+[IVX0-9]+\s*[:.]', line, re.I))
    hint_text = _key(labels + ' ' + captions)
    hints = _benchmark_hints(query)
    if hints and not all(hint in hint_text for hint in hints):
        return 0
    wanted = set()
    for metrics, generic in _DOMAINS:
        explicit = {metric for metric in metrics if re.search(
            r'(?<![A-Za-z0-9])' + re.escape(metric) + r'(?![A-Za-z0-9])', query, re.I)}
        # Resource-size labels vary between papers. Read their literal cells
        # together; this does not equate RAM/VRAM, disk size, units or boundaries.
        size_headers = {'size', 'memory', 'mem', 'storage', 'modelsize'}
        if explicit & size_headers:
            explicit.update(size_headers)
        wanted.update(explicit or (metrics if re.search(generic, query, re.I) else ()))
    headers = [metric for _, metrics in packet['groups'] for metric in metrics]
    matched = set()
    for column, header in enumerate(headers):
        metric = _key(header)
        if metric in wanted and any(re.search(r'[-+]?\d+(?:\.\d+)?', row[2][column])
                                    for row in packet['rows']):
            matched.add(metric)
    return len(matched)
