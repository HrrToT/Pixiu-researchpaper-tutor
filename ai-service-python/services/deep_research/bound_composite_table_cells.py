"""Check numeric slash series against literal same-cell display and exact metric roles."""
import re


_NUMBER = r'[+\-−]?\d+(?:\.\d+)?'
_SERIES = re.compile(
    rf'(?<![A-Za-z0-9_.+\-−/／]){_NUMBER}(?:\s*[/／]\s*{_NUMBER})+'
    r'(?![A-Za-z0-9_.%％]|\s*[/／])'
)
_NUMERIC_SLASH = re.compile(r'\d\s*[/／]\s*[+\-−]?\d')
_COMPOSITE_METRIC = re.compile(r'[A-Za-z][A-Za-z0-9.\-]*(?:\s*[/／]\s*[A-Za-z][A-Za-z0-9.\-]*)+')
_CLAUSE = re.compile(r'[。！？；!?;\n]|(?<!\d)\.(?=\s|$)|\.(?!\d)(?=\s|$)')
_LEAD_IN = r'\s*(?:为|是|[：:=]|\b(?:is|was|were|are)\b)?\s*'


def _compact(value):
    return re.sub(r'\s+', '', value).replace('／', '/')


def _literal_pattern(value):
    return r'\s*'.join(r'[/／]' if char == '/' else re.escape(char) for char in _compact(value))


def _bound_display(prefix, metric, dataset, method, method_visible, dataset_visible):
    metric_at_end = re.search(r'(?<![A-Za-z0-9_/／])' + _literal_pattern(metric) + _LEAD_IN + r'$', prefix, re.I)
    if not metric_at_end:
        return False
    context = prefix[:metric_at_end.start()]
    return method_visible(method, context) and dataset_visible(dataset, context)


def has_numeric_slash(text):
    return bool(_NUMERIC_SLASH.search(text))


def literal_dataset_visible(dataset, text):
    return all(
        re.search(r'(?<![A-Za-z0-9_+\-])' + r'\s+'.join(map(re.escape, label.split()))
                  + r'(?![A-Za-z0-9_+\-])', text, re.I)
        for label in dataset.split(' / ')
    )


def all_composite_series_bound(fields, cells, method_visible):
    """Every numeric slash must be part of an intact qualified display of one cell."""
    for field in fields:
        for clause in _CLAUSE.split(field):
            bound_spans = []
            for series in _SERIES.finditer(clause):
                matches = {identity for identity, dataset, method, metric, value in cells
                           if _COMPOSITE_METRIC.fullmatch(metric)
                           and _compact(series.group()) == _compact(value)
                           and len(metric.replace('／', '/').split('/')) == len(_compact(value).split('/'))
                           and _bound_display(clause[:series.start()], metric, dataset, method,
                                              method_visible, literal_dataset_visible)}
                if len(matches) == 1:
                    bound_spans.append(series.span())
            if any(not any(start <= slash.start() < slash.end() <= end for start, end in bound_spans)
                   for slash in _NUMERIC_SLASH.finditer(clause)):
                return False
    return True
