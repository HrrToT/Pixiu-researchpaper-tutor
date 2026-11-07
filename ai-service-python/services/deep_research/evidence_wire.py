"""Lossless repeated-key factoring for the experiment generation window."""
from copy import deepcopy

LEGEND=('Evidence summaries use {layouts:[field-name arrays],rows:[[layoutIndex,values]]}. '
    'Indices are zero-based. Zip the indicated layout with values to reconstruct each exact '
    'evidence object, including nested contexts and permissions. Absent keys stay absent; '
    'no scientific value or source permission is added by this encoding.')
SHORT_LEGEND=('Evidence {layouts:[keys],rows:[[i,values]]}: i is a zero-based layout index. '
    'Zip keys/values to recover exact rows, contexts and permissions. Missing keys stay absent; '
    'encoding grants no scientific approval.')


def encode(rows):
    layouts=[];packed=[]
    if not isinstance(rows,list):raise ValueError('invalid_evidence_rows')
    for row in rows:
        if not isinstance(row,dict) or any(not isinstance(k,str) for k in row):
            raise ValueError('invalid_evidence_row')
        layout=list(row)
        if layout not in layouts:layouts.append(layout)
        packed.append([layouts.index(layout),deepcopy(list(row.values()))])
    return {'layouts':layouts,'rows':packed}


def decode(packet):
    if not isinstance(packet,dict) or set(packet)!={'layouts','rows'}:
        raise ValueError('invalid_evidence_packet')
    layouts=packet['layouts'];rows=packet['rows']
    if (not isinstance(layouts,list) or not isinstance(rows,list)
            or any(not isinstance(k,list) or any(not isinstance(v,str) for v in k)
                or len(k)!=len(set(k)) for k in layouts)):
        raise ValueError('invalid_evidence_layout')
    result=[]
    for row in rows:
        if (not isinstance(row,list) or len(row)!=2 or type(row[0]) is not int
                or not 0<=row[0]<len(layouts) or not isinstance(row[1],list)
                or len(row[1])!=len(layouts[row[0]])):
            raise ValueError('invalid_evidence_values')
        result.append(dict(zip(layouts[row[0]],deepcopy(row[1]))))
    return result
