"""Locate visible, same-version marker explanations; never interpret or cite them."""
from collections import Counter
from copy import deepcopy
import re
from services.deep_research.table_evidence import visible_table_packet

_GROUPS=(('*','∗','⋆'),('†',),('‡',))
_CUE=re.compile(r'\b(?:marked|denot\w*|indicat\w*|asterisk|dagger|symbol)\b|星号|标记|标注|表示',re.I)
_MATCHED_RETRAINING = re.compile(
    r'(?<!not )(?<!never )\b(?:re[-\s]?train\w*)\b[^.!?]{0,330}\b(?:our|same|identical)\s+(?:\w+\s+){0,3}(?:platform|gpu|hardware)\b'
    r'[^.!?]{0,140}\b(?:marked|denoted|indicated)\s+(?:by|with)\b', re.I)
_MATCHED_MARKER = re.compile(_MATCHED_RETRAINING.pattern + r'\s*([*∗⋆†‡])', re.I)
GUIDANCE="""
Keep exact dataset/group and method row labels beside metric/value. A readable name
may precede the literal row label, never replace it. Preserve variant markers, dropping
only bibliography suffixes. Original code/configuration is not original published data.
Read the actual caption/note before calling a row original, re-trained, fine-tuned or
matched; marker meaning is paper-specific. Same-work/version marker matches below are
UNVERIFIED candidates, not proof of applicability. Resolve multiple candidates from the
actual quotations. If a note supplies provenance, cite BOTH that note and the table in
THAT claim. Another point's note citation does not support it; a note cannot verify cells
outside its own table quotations. Use only this target's existing source permissions.
An empty index is not evidence of no paper note. A missing current citation is not an
author-wide omission; do not turn review feedback into 'authors did not state/test it'.
A qualified inference needs its own premises, not an identical author conclusion.
Keep this index, E IDs and source-selection narration out of public prose.
"""


def _texts(row):
    text=[row.get('quote','')]
    context=None if row.get('contextOmitted') is True else row.get('sourceContext')
    if isinstance(context,dict):text.extend(context.get(k,'') for k in ('before','after'))
    elif isinstance(context,str):text.append(context)
    return [t for t in text if isinstance(t,str)]


def build(rows,owners,*,literal_ids,permissions=None):
    if not isinstance(rows,list) or not isinstance(owners,dict):raise ValueError('Invalid table-note navigation')
    if type(literal_ids) not in (set,list,tuple,frozenset) or any(not isinstance(e,str) or not e for e in literal_ids):raise ValueError('Invalid literal note sources')
    if permissions is not None and not isinstance(permissions,dict):raise ValueError('Invalid note permissions')
    if permissions is not None:permissions={c:[r for r in refs if isinstance(r,str)] for c,refs in permissions.items() if isinstance(c,str) and isinstance(refs,list)}
    counts=Counter(r.get('evidenceId') for r in rows if isinstance(r,dict) and isinstance(r.get('evidenceId'),str))
    def owner(eid):
        value=owners.get(eid)
        return tuple(value) if isinstance(value,(tuple,list)) and len(value)==2 and all(isinstance(v,str) and v.strip() for v in value) else None
    visible=[r for r in rows if isinstance(r,dict) and isinstance(r.get('evidenceId'),str)
        and counts[r['evidenceId']]==1 and r['evidenceId'] in literal_ids and owner(r['evidenceId'])]
    tables=[]
    for row in visible:
        if row.get('tableDataOmitted') is True or not isinstance(row.get('quote'),str):continue
        eid=row['evidenceId'];packet=visible_table_packet(row.get('tableData'),row.get('quote',''))
        if not packet or len({r[0] for r in packet['rows']})!=len(packet['rows']):continue
        for group in _GROUPS:
            marked=[{'rowNumber':r[0],'method':r[1],'marker':next(s for s in group if s in r[1])}
                    for r in packet['rows'] if any(s in r[1] for s in group)]
            if not marked:continue
            candidates=[]
            for note in visible:
                if owner(note['evidenceId'])!=owner(eid):continue
                found=False
                for text in _texts(note):
                    for symbol in group:
                        for match in re.finditer(re.escape(symbol),text):
                            if _CUE.search(text[max(0,match.start()-100):match.end()+100]):found=True;break
                        if found:break
                    if found:break
                if found:candidates.append(note['evidenceId'])
            if permissions is not None:
                candidates=[n for n in candidates if any(eid in refs and n in refs for refs in permissions.values())]
            if candidates:tables.append({'tableEvidenceId':eid,'markedRows':marked,
                'candidateNoteEvidenceIds':candidates,'applicabilityUnverified':True,'ambiguous':len(candidates)>1})
    result={'tables':tables}
    if permissions is not None:
        if not isinstance(permissions,dict):raise ValueError('Invalid note permissions')
        result['byClaim']={cid:[{'tableEvidenceId':t['tableEvidenceId'],
            'candidateNoteEvidenceIds':[e for e in t['candidateNoteEvidenceIds'] if e in refs]}
            for t in tables if t['tableEvidenceId'] in refs and any(e in refs for e in t['candidateNoteEvidenceIds'])]
            for cid,refs in permissions.items() if isinstance(cid,str) and isinstance(refs,list)}
    return deepcopy(result)


def matched_protocols(rows, owners):
    """Link only unambiguous, explicit same-platform retraining notes."""
    candidates = build(rows, owners, literal_ids=set(owners))
    by_id = {row['evidenceId']: row for row in rows}
    result = {}
    for table in candidates['tables']:
        options = table['markedRows']
        marked = options[0] if len(options) == 1 else None
        if marked is None:
            source = by_id[table['tableEvidenceId']]
            location = source.get('location') or {}
            if location.get('tableColumnMappingUnverified') is not False:
                continue
            packet = visible_table_packet(source.get('tableData'), source.get('quote', ''))
            if not packet:
                continue

            def bare(label):
                return re.sub(r'\s+|[*∗⋆†‡]|\[\s*\d+\s*\]', '', label).casefold()

            unmarked = Counter(bare(label) for _, label, _ in packet['rows']
                               if not any(marker in label for group in _GROUPS for marker in group))
            twins = [item for item in options if unmarked[bare(item['method'])] == 1]
            if len(twins) != 1:
                continue
            marked, = twins
        symbols = next(group for group in _GROUPS if marked['marker'] in group)
        suffix = r'\s*[' + re.escape(''.join(symbols)) + r']'
        explicit = [note for note in table['candidateNoteEvidenceIds']
                    if re.search(_MATCHED_RETRAINING.pattern + suffix, by_id[note].get('quote', ''), re.I)]
        if len(options) > 1:
            def explicitly_names_baseline(note):
                text = by_id[note].get('quote', '')
                match = re.search(r'\bre[-\s]?train\w*\s+(.{1,160}?)\s+using\b', ' '.join(text.split()), re.I)
                names = re.split(r'\s+and\s+|\s*,\s*', match[1], flags=re.I) if match else []
                return bare(marked['method']) in {bare(name) for name in names}

            explicit = [note for note in explicit if explicitly_names_baseline(note)]
        if len(explicit) == 1:
            result[table['tableEvidenceId']] = {'rowNumber': marked['rowNumber'],
                                               'noteEvidenceId': explicit[0]}
    return result


def prefers_protocol_note(record):
    from services.deep_research.comparison_joint_reports import _SINGLE_NUMERIC_EXAMPLE
    from services.deep_research.request_context import effective_question

    if (record.get('comparisonJointReportsContractVersion') != 16
            or record.get('state', {}).get('outputKind') != 'paper_comparison'):
        return False
    question = effective_question(record)
    return any(_SINGLE_NUMERIC_EXAMPLE.search(layer)
               for layer in getattr(question, 'instruction_layers', (str(question),)))


def has_protocol_note(text):
    return isinstance(text, str) and bool(_MATCHED_MARKER.search(text))


def retain_local_protocol_note(rows, candidates, record, query, limit):
    """Keep one original note when the local results already contain a marked table."""
    from services.deep_research.measurement_table_navigation import planned_query_priority

    pdf_protocol = record.get('comparisonEvaluationProtocolVersion') in (6, 7, 8, 9)
    explicit_benchmark = pdf_protocol and re.search(r'\bbaseline\b', query, re.I) and re.search(
        r'\bbenchmark\b', query, re.I)
    if (limit < 2 or len(rows) > limit or not prefers_protocol_note(record)
            or not (planned_query_priority(query) or explicit_benchmark)):
        return rows

    def page_identity(row):
        metadata = row.get('metadata') or {}
        return (metadata.get('id') or row.get('pdfId'), metadata.get('index_version') or row.get('versionId'),
                (row.get('location') or {}).get('page'))

    markers_by_page = {}
    for row in rows:
        identity = page_identity(row)
        if all(identity):
            for _, label, _ in (row.get('tableData') or {}).get('rows', []):
                for group in _GROUPS:
                    if any(symbol in label for symbol in group):
                        markers_by_page.setdefault(identity, set()).update(group)
    if not markers_by_page:
        return rows

    def matches(row):
        text = row.get('text')
        match = _MATCHED_MARKER.search(text) if isinstance(text, str) else None
        metadata = row.get('metadata') or {}
        return (match and match[1] in markers_by_page.get(page_identity(row), ())
                and not row.get('tableData') and (not metadata or
                    (metadata.get('text_source') == 'pdf_page_text' and metadata.get('body_extraction_version') == 1)))

    if any(matches(row) for row in rows):
        return rows
    note = next((row for row in candidates if matches(row)
                 and row['sourceId'] not in {source['sourceId'] for source in rows}), None)
    if note is None:
        return rows
    if len(rows) < limit:
        return [*rows, note]
    # A generic hit can occupy the first slot; keep tables and targeted premises.
    replaceable_modes = {'indexed_hybrid', 'pdf_lexical_fallback'} if pdf_protocol else {'indexed_hybrid'}
    replace = next((i for i in range(len(rows) - 1, -1, -1)
                    if not rows[i].get('tableData') and rows[i].get('retrievalMode') in replaceable_modes), None)
    return [*rows[:replace], note, *rows[replace + 1:]] if replace is not None else rows
