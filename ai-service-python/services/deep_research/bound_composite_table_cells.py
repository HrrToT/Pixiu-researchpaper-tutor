"""Check numeric slash series against literal same-cell display and exact metric roles."""
import re

from services.deep_research.publication_identity import validated
from services.deep_research.source_revisions import explicit_revisions
from services.deep_research.table_evidence import visible_table_packet


_NUMBER = r'[+\-−]?\d+(?:\.\d+)?'
_SERIES = re.compile(
    rf'(?<![A-Za-z0-9_.+\-−/／]){_NUMBER}(?:\s*[/／]\s*{_NUMBER})+'
    r'(?![A-Za-z0-9_.%％]|\s*[/／])'
)
_NUMERIC_SLASH = re.compile(r'\d\s*[/／]\s*[+\-−]?\d')
_COMPOSITE_METRIC = re.compile(r'[A-Za-z][A-Za-z0-9.\-]*(?:\s*[/／]\s*[A-Za-z][A-Za-z0-9.\-]*)+')
_CLAUSE = re.compile(r'[。！？；!?;\n]|(?<!\d)\.(?=\s|$)|\.(?!\d)(?=\s|$)')
_LEAD_IN = r'\s*(?:为|是|[：:=]|\b(?:is|was|were|are)\b)?\s*'
_SHORT_REVISION = re.compile(r'(?<![A-Za-z0-9_.-])v[1-9]\d*(?![A-Za-z0-9_-]|\.\d)', re.I)


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


def evidence_revision(source):
    publication = validated(source.get('sourcePublicationIdentity'), source.get('contentHash'))
    if publication:
        return publication['displayId']
    version = source.get('sourceVersionId')
    if not isinstance(version, str) or not source.get('contentHash'):
        return None
    revisions = explicit_revisions(version)
    return next((revision for group in revisions.values() for revision in group
                 if version.casefold() in (revision, revision.removeprefix('arxiv:'))
                 and source.get('sourceWorkId') == revision.rsplit('v', 1)[0]), None)


def _matched_identities(matches, context, revisions):
    full = {key for group in explicit_revisions(context).values() for key in group}
    short = {item.casefold() for item in _SHORT_REVISION.findall(context)}
    if not full and not short:
        return matches if len(matches) == 1 else set()
    by_revision = {}
    for identity in matches:
        revision = revisions.get(identity)
        if revision and (revision in full if full else revision[revision.rfind('v'):] in short):
            by_revision.setdefault(revision, set()).add(identity)
    if not by_revision or any(len(identities) != 1 for identities in by_revision.values()):
        return set()
    if full:
        if set(by_revision) != full or (short and not short <= {r[r.rfind('v'):] for r in full}):
            return set()
    elif (len({r.rsplit('v', 1)[0] for r in by_revision}) != 1
          or {r[r.rfind('v'):] for r in by_revision} != short):
        return set()
    return set().union(*by_revision.values())


def all_composite_series_bound(fields, cells, method_visible, revisions=None):
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
                if revisions is None:
                    matched = matches if len(matches) == 1 else set()
                else:
                    matched = _matched_identities(matches, clause, revisions)
                if matched:
                    bound_spans.append(series.span())
            if any(not any(start <= slash.start() < slash.end() <= end for start, end in bound_spans)
                   for slash in _NUMERIC_SLASH.finditer(clause)):
                return False
    return True


def drafting_guidance(record):
    """Add display guidance only for a new run that has a composite cell."""
    version = record.get('boundCompositeTableCellsVersion')
    if type(version) is not int or version != 2:
        return ''
    for evidence in record.get('state', {}).get('evidence', []):
        packet = visible_table_packet(evidence.get('tableData'), evidence.get('quote', ''))
        if not packet:
            continue
        metrics = [metric for _, columns in packet['groups'] for metric in columns]
        if any(_COMPOSITE_METRIC.fullmatch(metric) and has_numeric_slash(value)
               for _, _, values in packet['rows'] for metric, value in zip(metrics, values)):
            return ('\nFor a slash-delimited metric in one cell, give its complete metric, dataset, '
                    'method and exact value together. When comparing revisions, use a separate clause '
                    'for each revision and bind that clause to its own cited cell. Use the source '
                    'publicationIdentity for the revision label when present.')
    return ''
