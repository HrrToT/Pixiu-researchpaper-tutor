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


def _key(text):
    text = re.sub(r'\([^)]*\)|\[[^]]*\]', '', text)
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def _benchmark_hints(query):
    # Only literal name-like targets, not an inferred benchmark from the paper title.
    names = re.findall(r'\b(?:on|dataset|benchmark)\s+([A-Za-z][A-Za-z0-9&_\-]*)', query, re.I)
    names += re.findall(r'\b(?:Dataset|Benchmark)[-_][A-Za-z0-9_-]+', query, re.I)
    names += re.findall(r'([A-Za-z][A-Za-z0-9&_\-]*)(?:数据集|基准)', query)
    return {_key(name) for name in names if name.casefold() not in _GENERIC}


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
