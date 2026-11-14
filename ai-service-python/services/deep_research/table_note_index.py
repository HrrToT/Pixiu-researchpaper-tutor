"""Locate visible, same-version marker explanations; never interpret or cite them."""
from collections import Counter
from copy import deepcopy
import re
from services.deep_research.table_evidence import visible_table_packet

_GROUPS=(('*','∗','⋆'),('†',),('‡',))
_CUE=re.compile(r'\b(?:marked|denot\w*|indicat\w*|asterisk|dagger|symbol)\b|星号|标记|标注|表示',re.I)
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
