"""Select requested literal measurements; do not convert units or approve claims."""
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from services.deep_research.source_continuity import needs_preceding_context

_MEASUREMENT = re.compile(
    r'(?<![A-Za-z0-9_.,/+\-])([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*-?\s*'
    r'(milliseconds?|msecs?|ms|seconds?|secs?|s|frames\s*/\s*s|frames\s+per\s+second|'
    r'fps|mb|gb|db|%|毫秒|秒|帧/秒|帧每秒)(?![A-Za-z])', re.I)
_UNITS = {'millisecond':'ms','milliseconds':'ms','msec':'ms','msecs':'ms','ms':'ms','毫秒':'ms',
    'second':'s','seconds':'s','sec':'s','secs':'s','s':'s','秒':'s',
    'frames/s':'fps','framespersecond':'fps','fps':'fps','帧/秒':'fps','帧每秒':'fps',
    'mb':'mb','gb':'gb','db':'db','%':'%'}


def measurements(text):
    result = set()
    for match in _MEASUREMENT.finditer(text):
        if len(match[1]) > 128:
            continue
        try:
            number = Decimal(match[1])
        except InvalidOperation:
            continue
        result.add((number, _UNITS[re.sub(r'\s+', '', match[2]).lower()]))
    return result


def _body(row):
    text = re.split(r'\bContent:\s*', row.get('text',''), maxsplit=1)[-1]
    return re.sub(r'^\s*(?:Paper|Section):[^\n]*(?:\n|$)', '', text, flags=re.M)


def include_requested_measurements(indexed, candidates, query, owned_id, limit):
    """Use at most two existing slots, retaining context and exact source text."""
    selected = list(indexed[:limit]); targets = measurements(query)
    if not selected or not targets or limit < 2:
        return selected
    anchor = selected[0]; meta = anchor.get('metadata') or {}; version = meta.get('index_version')
    if (anchor.get('pdfId') != owned_id or meta.get('id') != owned_id
            or not isinstance(version,str) or not re.fullmatch(r'[0-9a-f]{16}',version)):
        return selected
    owned = [r for r in candidates if r.get('pdfId') == owned_id
             and (r.get('metadata') or {}).get('id') == owned_id
             and (r.get('metadata') or {}).get('index_version') == version
             and isinstance(r.get('sourceId'),str) and r['sourceId']
             and type((r.get('metadata') or {}).get('chunk_index')) is int]
    ids = Counter(r['sourceId'] for r in owned); chunks = Counter(r['metadata']['chunk_index'] for r in owned)
    owned = [r for r in owned if ids[r['sourceId']] == chunks[r['metadata']['chunk_index']] == 1]
    protected = {anchor.get('sourceId')}; covered = set()
    for row in selected:
        matches = measurements(_body(row)) & targets
        covered |= matches
        if matches:
            protected.add(row.get('sourceId'))
        if row.get('contextForSourceId'):
            protected.update((row['sourceId'],row['contextForSourceId']))
    ranked = sorted(owned, key=lambda r: (-len(measurements(_body(r)) & targets),r['metadata']['chunk_index']))
    added = 0
    for detail in ranked:
        matches = measurements(_body(detail)) & (targets - covered)
        if not matches or detail['sourceId'] in {r.get('sourceId') for r in selected}:
            continue
        additions = [{**detail,'retrievalMode':'indexed_requested_measurement'}]
        required = set()
        if needs_preceding_context(detail):
            dm = detail['metadata']; section = dm.get('section_title')
            previous = [r for r in owned if r['metadata']['chunk_index'] == dm['chunk_index'] - 1
                        and isinstance(section,str) and section.strip()
                        and r['metadata'].get('section_title') == section]
            if len(previous) != 1:
                continue
            required.add(previous[0]['sourceId'])
            if previous[0]['sourceId'] not in {r.get('sourceId') for r in selected}:
                additions.insert(0,{**previous[0],'retrievalMode':'indexed_preceding_context',
                                    'contextForSourceId':detail['sourceId']})
        if added + len(additions) > 2:
            continue
        removable = [i for i,r in enumerate(selected) if r.get('sourceId') not in protected | required]
        needed = max(0,len(selected)+len(additions)-limit)
        if needed > len(removable):
            continue
        for index in sorted(removable[-needed:] if needed else [],reverse=True):
            selected.pop(index)
        selected[1+added:1+added] = additions
        selected = [{**r,'contextForSourceId':detail['sourceId']} if r.get('sourceId') in required
                    and not r.get('contextForSourceId') else r for r in selected]
        added += len(additions)
        protected.update(r['sourceId'] for r in additions)
        protected |= required; covered |= matches
        if covered >= targets or added >= 2:
            break
    return selected
