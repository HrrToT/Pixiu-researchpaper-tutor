"""Identify ambiguous qualitative comparisons against variant rows."""

import re

from services.deep_research.measurement_table_navigation import benchmark_metric
from services.deep_research.table_evidence import visible_table_packet


MARKER = r'[*∗⋆†‡]'
REFERENCE = re.compile(r'\s*\[\d+\]\s*$')
DIRECTION = re.compile(
    r'较[高低好差快慢大少小多]|更[高低好差快慢大少小多]|[高低优劣快慢][于於]|'
    r'提升|下降|优于|超过|不及|\b(?:higher|lower|better|worse|faster|slower|outperform\w*)\b', re.I)
UNMARKED = r'(?:(?:未标星|未加星)(?:号)?|不带星号|无星号|unmarked)'
UNMARKED_BEFORE = re.compile(UNMARKED + r'的?\s*$', re.I)
UNMARKED_AFTER = re.compile(r'^\s*[(（]\s*' + UNMARKED + r'\s*[)）]', re.I)


def variant_groups(rows):
    methods = {}
    for row in rows:
        label = REFERENCE.sub('', row[1])
        base = ' '.join(re.sub(MARKER, '', label).split())
        if base:
            methods.setdefault(base.casefold(), []).append(row)
    return [group for group in methods.values() if len(group) > 1 and len({row[1] for row in group}) > 1
            and any(re.search(MARKER, row[1]) for row in group)]


def _table_key(item):
    location = item.get('location') or {}
    owner = tuple(item.get(k) for k in ('sourceWorkId', 'sourceVersionId', 'contentHash'))
    page = location.get('page')
    if (all(isinstance(value, str) and value for value in owner)
            and type(page) is int and page > 0 and location.get('pageResolution') == 'exact'):
        return (*owner, page)
    return None


def _compact(text):
    return re.sub(r'\s+', '', text).casefold()


def _raw_rows_match(item, rows):
    # A separate plain-text extraction counts only if it visibly contains the
    # alternative rows. Proximity on the same page alone does not link tables.
    lines = [_compact(line) for line in item.get('quote', '').splitlines()]
    prefixes = [_compact(label + values[0]) for _, label, values in rows]
    return all(any(line.startswith(prefix) for line in lines) for prefix in prefixes)


def index(evidence):
    tables = []
    for item in evidence:
        if (item.get('verification', {}).get('literal') != 'passed'
                or (item.get('location') or {}).get('tableColumnMappingUnverified') is True):
            continue
        packet = visible_table_packet(item.get('tableData'), item.get('quote', ''))
        if not packet:
            continue
        metrics = {re.sub(r'[↑↓]\s*$', '', metric).strip() for _, names in packet['groups']
                   for metric in names if benchmark_metric(metric)}
        groups = variant_groups(packet['rows']) if metrics else []
        if groups:
            tables.append((item, packet['rows'], groups, metrics))
    return tables


def ambiguous_rows(text, support, tables):
    """Return exact candidate labels, without choosing a baseline or a direction."""
    clauses = [line for line in re.split(r'[。！？；!?;\n]+|(?<!\d)\.(?!\d)', text)
               if DIRECTION.search(line)]
    for item, rows, groups, metrics in tables:
        # ASCII metric names often appear directly after Chinese prose.
        metric_pattern = r'(?<![A-Za-z0-9_])(?:' + '|'.join(re.escape(metric) for metric in sorted(metrics)) + r')(?![A-Za-z])'
        for group in groups:
            table_key = _table_key(item)
            if not any(cited['evidenceId'] == item['evidenceId']
                       or (table_key is not None and _table_key(cited) == table_key and _raw_rows_match(cited, group))
                       for cited in support):
                continue
            base = re.sub(MARKER, '', REFERENCE.sub('', group[0][1])).strip()
            group_labels = {row[1] for row in group}
            # Match longer named methods first, e.g. Compressed 3D-GS
            # must not become an unqualified mention of the 3D-GS baseline.
            other_names = {re.sub(MARKER, '', REFERENCE.sub('', row[1])).strip()
                           for row in rows if row[1] not in group_labels}
            names = sorted({base, *other_names} - {''}, key=lambda name: (-len(name), name))
            pattern = re.compile(r'(?<![A-Za-z0-9_])(?P<name>' + '|'.join(
                r'\s+'.join(re.escape(part) for part in name.split()) for name in names
            ) + r')(?![A-Za-z0-9_])(?P<marker>\s*' + MARKER + r')?(?P<reference>\s*\[\d+\])?', re.I)
            unmarked_labels = {_compact(label) for label in group_labels if not re.search(MARKER, label)}
            marked_symbols = {symbol for label in group_labels for symbol in re.findall(MARKER, label)}
            if marked_symbols.intersection('*∗⋆'):
                marked_symbols.update('*∗⋆')
            for clause in clauses:
                if not re.search(metric_pattern, clause, re.I):
                    continue
                matches = [m for m in pattern.finditer(clause) if _compact(m['name']) == _compact(base)]
                for match in matches:
                    if match['marker']:
                        qualified = match['marker'].strip() in marked_symbols
                    else:
                        qualified = (bool(unmarked_labels) and (
                            UNMARKED_BEFORE.search(clause[:match.start()])
                            or UNMARKED_AFTER.search(clause[match.end():])
                            or match['reference'] and _compact(match[0]) in unmarked_labels))
                    if not qualified:
                        return [row[1] for row in group]
    return []
