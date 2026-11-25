"""Render model-selected cells using their verified PDF revisions."""
from collections import defaultdict
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
GUIDANCE = ('For the same row across revisions, put exact bound cells in a reported claim. '
            'The app formats their revision labels from the PDF. In conclusions explain the difference '
            'without repeating numbers already reported in those rows.')


def _resolve(claim, own, number):
    bindings = claim.get('tableBindings')
    if not isinstance(bindings, list) or not 2 <= len(bindings) <= 32:
        return None
    normalized = []
    groups = defaultdict(dict)
    work_ids, row_labels, coordinates = set(), set(), set()
    owners_by_revision = defaultdict(set)
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
        if len(entries) != 1:
            return None
        cell = entries[0]
        label = ' '.join(cell['method'].split())
        column = ' · '.join(' '.join(part.split()) for part in (cell['group'], cell['metric']) if part.strip())
        if not _LABEL.fullmatch(label) or not _LABEL.fullmatch(column) or not _SCALAR.fullmatch(cell['value']):
            return None
        revision = publication['revision']
        identity = (revision, column)
        if identity in coordinates or not re.fullmatch(r'v[1-9]\d*', revision):
            return None
        coordinates.add(identity)
        groups[revision][column] = cell['value']
        work_ids.add(publication['workId'])
        owners_by_revision[revision].add(source['ownerMaterialId'])
        row_labels.add(label)
        normalized.append(binding)
    if (len(work_ids) != 1 or len(row_labels) != 1 or len(groups) < 2
            or any(len(owners) != 1 for owners in owners_by_revision.values())):
        return None
    first_columns = list(next(iter(groups.values())))
    if any(set(values) != set(first_columns) for values in groups.values()):
        return None
    label, = row_labels
    return normalized, label, first_columns, groups


def materialize(report, evidence, number):
    """Keep draft coverage and citations; use literal values for a matched row across revisions."""
    supplied = {row['evidenceId']: row for row in evidence}
    claims = []
    fixed = []
    for claim in report['claims']:
        if (not isinstance(claim, dict) or claim.get('kind') != 'reported' or not claim.get('claimId')
                or not isinstance(claim.get('evidenceRefs'), list) or not claim.get('evidenceRefs')
                or any(not isinstance(ref, str) or ref not in supplied for ref in claim['evidenceRefs'])
                or claim.get('scopeExpression') or claim.get('body')):
            claims.append(claim)
            continue
        own = {ref: supplied[ref] for ref in claim['evidenceRefs']}
        matched = _resolve(claim, own, number)
        if not matched:
            claims.append(claim)
            continue
        bindings, label, columns, revisions = matched
        order = sorted(revisions, key=lambda item: int(item[1:]))
        values = '，'.join(revision + ' ' + '、'.join(revisions[revision][key] for key in columns) for revision in order)
        text = f'表 {number} {label}（' + '、'.join(columns) + f'）依次为 {values}。'
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
