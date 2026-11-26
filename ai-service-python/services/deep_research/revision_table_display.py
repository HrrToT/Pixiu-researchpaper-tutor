"""Render model-selected cells using their verified PDF revisions."""
from collections import defaultdict
from decimal import Decimal
import re

from services.deep_research.publication_identity import owned_evidence_publication
from services.deep_research.named_table_scope import select
from services.deep_research.table_bindings import bound_table_context


_FIELDS = {'evidenceId', 'rowNumber', 'groupIndex', 'metric', 'value'}
_ALTERNATE_FIELDS = {'evidenceId', 'sourceRowNumber', 'groupIndex', 'metricKey', 'value'}
_SCALAR = re.compile(r'[+−-]?\d+(?:\.\d+)?%?')
_LABEL = re.compile(r'[\w .()+%\-/·]{1,96}')
_REVISION = re.compile(r'(?<![A-Za-z0-9_.-])v[1-9]\d*(?![A-Za-z0-9_.-])', re.I)
_DECIMAL = re.compile(r'(?<![A-Za-z0-9_.-])\d+\.\d+(?![A-Za-z0-9.%])')
_MEASURED = re.compile(r'\bmeasured\s+(?:the\s+)?([^.!?;\n]{1,96})', re.I)
_PERCENT = re.compile(r'(?<![A-Za-z\d.])\d+(?:\.\d+)?\s*[%％]')
_COMMON_FINDING = re.compile(
    r'(?:两|各|不?同)版[^。！？]{0,24}共同[^。！？]{0,12}(?:结论|发现|结果)'
    r'|\b(?:shared|common) (?:findings?|conclusions?) (?:across|in) (?:both|the) (?:revisions|versions)\b',
    re.I,
)
GUIDANCE = ('For the same row across revisions, put exact bound cells in a reported claim. '
            'The app formats their revision labels from the PDF. In conclusions explain the difference '
            'without repeating numbers already reported in those rows.')
JUDGEMENT_GUIDANCE = (
    'Bind measured values once in reported prose; give the dataset and conditions. '
    'Each binding has exactly evidenceId,rowNumber,groupIndex,metric,value. '
    'Use prose for supported differences and shared findings. Use boundary only for an unresolved claim '
    'such as the cause of a difference; do not list table measurements as observedSettings.'
)
REQUESTED_FINDINGS_GUIDANCE = (
    'Bind original measurements once as reported cells. Keep the dataset and exact requested settings. '
    'Each binding has evidenceId,rowNumber,groupIndex,metric,value. State observed changes in prose. '
    'For a shared finding, compare the requested setting to each requested baseline using the bound cells '
    'from both revisions; state their ordering, including where the setting is worse. '
    'A broader caption does not substitute for that answer. Use boundary only for unresolved questions such as cause.'
)


def _metric_key(text):
    return ''.join(text.casefold().split())


def _table_identity(source):
    return source.get('ownerMaterialId'), source.get('sourceVersionId'), (source.get('location') or {}).get('table')


def _unique_coordinate(binding, source, *, measured_names=(), peers=()):
    """Resolve a flat column reference within the same cited row and value."""
    from services.deep_research.table_evidence import visible_table_packet

    packet = visible_table_packet(source.get('tableData'), source.get('quote', ''))
    if not packet or type(binding['rowNumber']) is not int or type(binding['groupIndex']) is not int:
        return None
    row = next((row for row in packet['rows'] if row[0] == binding['rowNumber']), None)
    if row is None:
        return None
    matches = []
    value_matches = []
    offset = 0
    for group, (label, metrics) in enumerate(packet['groups']):
        for index, metric in enumerate(metrics):
            if binding['value'] == row[2][offset + index]:
                cell = {**binding, 'groupIndex': group, 'metric': metric}
                value_matches.append(cell)
                if binding['metric'] in (metric, f'{label} / {metric}'):
                    matches.append(cell)
        offset += len(metrics)
    if not matches and isinstance(binding['metric'], str) and measured_names == {_metric_key(binding['metric'])}:
        if len(value_matches) == 1:
            matches = value_matches
        elif len(value_matches) > 1:
            # A model can number its selected columns instead of copying their
            # headers. Reuse a slot only when the other cited rows of this same
            # PDF table identify exactly one corresponding verified column.
            coordinates = set()
            for other, row_source in peers:
                if (other.get('rowNumber') == binding['rowNumber'] or other.get('groupIndex') != binding['groupIndex']
                        or other.get('metric') != binding['metric']):
                    continue
                anchored = _unique_coordinate(other, row_source, measured_names=measured_names)
                if anchored is not None:
                    coordinates.add((anchored['groupIndex'], anchored['metric']))
            if len(coordinates) == 1:
                matches = [cell for cell in value_matches if (cell['groupIndex'], cell['metric']) in coordinates]
    return matches[0] if len(matches) == 1 else None


def _resolve(claim, own, number, *, multiple_rows, reconcile_coordinates, measured_metric_alias=False,
             single_revision_display=False):
    bindings = claim.get('tableBindings')
    if not isinstance(bindings, list) or not 2 <= len(bindings) <= 32:
        return None
    normalized = []
    groups = defaultdict(dict)
    work_ids = set()
    owners_by_revision = defaultdict(set)
    measured_names = defaultdict(set)
    peer_rows = defaultdict(list)
    if measured_metric_alias:
        # A caption can be in a different passage from the row. Keep it
        # within this claim's cited, verified table and exact PDF revision.
        eligible_tables = {}
        for eid, source in own.items():
            table = _table_identity(source)
            if (table[2] and owned_evidence_publication(source)
                    and eid in select([source], number)[1]):
                eligible_tables[eid] = table
                measured_names[table].update(_metric_key(match[1]) for match in _MEASURED.finditer(source['quote']))
        for binding in bindings:
            if isinstance(binding, dict) and set(binding) == _FIELDS and isinstance(binding['evidenceId'], str):
                eid = binding['evidenceId']
                if eid in eligible_tables:
                    peer_rows[eligible_tables[eid]].append((binding, own[eid]))
    for binding in bindings:
        if not isinstance(binding, dict):
            return None
        if set(binding) == _ALTERNATE_FIELDS:
            binding = {**{k:v for k,v in binding.items() if k not in ('sourceRowNumber','metricKey')},
                       'rowNumber':binding['sourceRowNumber'], 'metric':binding['metricKey']}
        if set(binding) != _FIELDS or not isinstance(binding['evidenceId'], str):
            return None
        source = own.get(binding['evidenceId'], {})
        publication = owned_evidence_publication(source)
        if not publication or (source.get('location') or {}).get('table') is None:
            return None
        if binding['evidenceId'] not in select([source], number)[1]:
            return None
        entries = bound_table_context({**claim, 'tableBindings': [binding]}, [source])
        if not entries and reconcile_coordinates:
            table = _table_identity(source)
            binding = _unique_coordinate(binding, source, measured_names=measured_names.get(table, ()),
                                         peers=peer_rows.get(table, ()))
            if binding is not None:
                entries = bound_table_context({**claim, 'tableBindings': [binding]}, [source])
        if len(entries) != 1:
            return None
        cell = entries[0]
        label = ' '.join(cell['method'].split())
        column = ' · '.join(' '.join(part.split()) for part in (cell['group'], cell['metric']) if part.strip())
        if not _LABEL.fullmatch(label) or not _LABEL.fullmatch(column) or not _SCALAR.fullmatch(cell['value']):
            return None
        revision = publication['revision']
        coordinate = (label, column)
        if not re.fullmatch(r'v[1-9]\d*', revision) or coordinate in groups[revision]:
            return None
        groups[revision][coordinate] = cell['value']
        work_ids.add(publication['workId'])
        owners_by_revision[revision].add(source['ownerMaterialId'])
        normalized.append(binding)
    if (len(work_ids) != 1 or len(groups) < (1 if single_revision_display else 2)
            or any(len(owners) != 1 for owners in owners_by_revision.values())):
        return None
    first = next(iter(groups.values()))
    if any(values.keys() != first.keys() for values in groups.values()):
        return None
    labels = list(dict.fromkeys(label for label, _ in first))
    if len(labels) != 1 and not multiple_rows:
        return None
    columns = [column for label, column in first if label == labels[0]]
    if set(first) != {(label, column) for label in labels for column in columns}:
        return None
    return normalized, labels, columns, groups


def _common_order(question, labels, columns, revisions, bindings, cited):
    if not question or not _COMMON_FINDING.search(question) or len(columns) < 3:
        return ''
    requested = {Decimal(v[:-1].strip()) for v in _PERCENT.findall(question)}
    selected = {Decimal(v[:-1].strip()) for col in columns for v in _PERCENT.findall(col)}
    if selected != requested:
        return ''
    # Matching table coordinates alone do not identify a shared metric. Require
    # a single measured quantity named in the cited table text of each PDF.
    measures_by_table = defaultdict(set)
    for row in cited.values():
        for match in _MEASURED.finditer(row.get('quote', '')):
            measure = match[1]
            if re.search(r'\b(?:and|or)\b|[,/]', measure, re.I):
                continue
            measures_by_table[_table_identity(row)].add(_metric_key(measure))
    table_ids = {_table_identity(cited[binding['evidenceId']]) for binding in bindings}
    common_measures = set.intersection(*(measures_by_table[table_id] for table_id in table_ids))
    if len(common_measures) != 1 or any(measures_by_table[table_id] != common_measures for table_id in table_ids):
        return ''
    units = {value.endswith('%') for revision in revisions.values() for value in revision.values()}
    if len(units) != 1:
        return ''
    common = None
    for revision in revisions.values():
        for label in labels:
            values = {column: Decimal(revision[label, column].rstrip('%').replace('−', '-')) for column in columns}
            order = sorted(columns, key=values.__getitem__)
            if len(set(values.values())) != len(columns) or (common is not None and order != common):
                return ''
            common = order
    return '各版所列模型的数值均从低到高为 ' + '、'.join(common) + '。'


def materialize(report, evidence, number, *, multiple_rows=False, reconcile_coordinates=False,
                excluded_claim_ids=(), measured_metric_alias=False, shared_findings_question=None,
                single_revision_display=False):
    """Render matching PDF cells once while retaining draft coverage and citations."""
    supplied = {row['evidenceId']: row for row in evidence}
    claims = []
    fixed = []
    for claim in report['claims']:
        if (not isinstance(claim, dict) or claim.get('kind') != 'reported' or not claim.get('claimId')
                or claim['claimId'] in excluded_claim_ids
                or not isinstance(claim.get('evidenceRefs'), list) or not claim.get('evidenceRefs')
                or any(not isinstance(ref, str) or ref not in supplied for ref in claim['evidenceRefs'])
                or claim.get('scopeExpression') or claim.get('body')):
            claims.append(claim)
            continue
        own = {ref: supplied[ref] for ref in claim['evidenceRefs']}
        matched = _resolve(claim, own, number, multiple_rows=multiple_rows,
                           reconcile_coordinates=reconcile_coordinates, measured_metric_alias=measured_metric_alias,
                           single_revision_display=single_revision_display)
        if not matched:
            claims.append(claim)
            continue
        bindings, labels, columns, revisions = matched
        if len(revisions) == 1:
            # Preserve the author's measurement context and existing prose.
            # Each canonical header belongs to the same already-bound cells.
            # Ordinary numeric and semantic checks still validate the claim.
            missing = [column for column in columns if column not in claim['text']]
            if not missing:
                claims.append(claim)
                continue
            text = claim['text'].rstrip() + '（原表列 ' + '、'.join(missing) + '）'
            claims.append({**claim, 'text':text, 'tableBindings':bindings})
            fixed.append(claim['claimId'])
            continue
        order = sorted(revisions, key=lambda item: int(item[1:]))
        values = {
            label: '，'.join(revision + ' ' + '、'.join(revisions[revision][label, column] for column in columns)
                            for revision in order)
            for label in labels
        }
        heading = '、'.join(columns)
        if len(labels) == 1:
            label, = labels
            text = f'表 {number} {label}（{heading}）依次为 {values[label]}。'
        else:
            rows = '；'.join(f'{label} 为 {values[label]}' for label in labels)
            text = f'表 {number}（{heading}）{rows}。'
        text += _common_order(shared_findings_question, labels, columns, revisions, bindings, own)
        claims.append({**claim, 'text': text, 'tableBindings': bindings})
        fixed.append(claim['claimId'])
    return {**report, 'claims': claims}, fixed


def contradictory_revision_values(claim, support, number):
    """Reject explicitly attributed foreign-version operands, without approving any others."""
    from services.deep_research.table_evidence import visible_table_packet

    text = claim.get('text', '')
    if not isinstance(text, str):
        return False
    labels = list(_REVISION.finditer(text))
    if len({match[0].casefold() for match in labels}) < 2:
        return False
    values = defaultdict(set)
    works = set()
    for row in support:
        publication = owned_evidence_publication(row)
        if not publication or row['evidenceId'] not in select([row], number)[1]:
            continue
        packet = visible_table_packet(row.get('tableData'), row.get('quote', ''))
        if packet:
            works.add(publication['workId'])
            values[publication['revision']].update(value for _, _, cells in packet['rows'] for value in cells)
    if len(works) != 1 or len(values) < 2:
        return False
    known = set().union(*values.values())
    for i, match in enumerate(labels):
        revision = match[0].casefold()
        if revision not in values:
            continue
        end = labels[i+1].start() if i+1 < len(labels) else len(text)
        clause = re.split('[。！？；;\n]', text[match.end():end], maxsplit=1)[0]
        if any(value in known and value not in values[revision] for value in _DECIMAL.findall(clause)):
            return True
    return False
