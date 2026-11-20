"""Navigation over already visible table metadata; never evidence approval."""
from collections import Counter
from copy import deepcopy
from services.deep_research.table_evidence import visible_table_packet


GUIDANCE = '''
Condition-source navigation below copies exact visible table group/method labels.
It is NOT scientific support, a method alias or a replacement for the quotations.
For a dataset/setting observation, locate the actual method in the relevant group
and cite that own permitted E source. A nearby related-work dataset name does not
establish the proposed method's evaluated setting. Check the full quote/context.
Do not infer that a group label establishes causation, comparable protocols,
quality, universal scope or absence of other experiments. Empty/missing entries
mean no indexed visible table, not no evidence in the acquired pool or paper.
Marked column mappings remain UNVERIFIED; check original headers/context before
using them. The index grants no geometry or factual approval. Permissions stay
unchanged; never output this navigation in the answer.
'''


def build(rows,permissions,*,literal_ids):
    if not isinstance(rows,list) or not isinstance(permissions,dict):
        raise ValueError('Invalid condition navigation input')
    if type(literal_ids) not in (set,list,tuple,frozenset) or any(not isinstance(eid,str) or not eid for eid in literal_ids):
        raise ValueError('Invalid literal source identities')
    eligible=set(literal_ids)
    permissions={key:[ref for ref in refs if isinstance(ref,str)]
        for key,refs in permissions.items() if isinstance(key,str) and isinstance(refs,list)}
    permitted={ref for refs in permissions.values() for ref in refs}
    counts=Counter(row.get('evidenceId') for row in rows if isinstance(row,dict) and isinstance(row.get('evidenceId'),str))
    tables=[]
    for row in rows:
        if not isinstance(row,dict):continue
        eid=row.get('evidenceId')
        if not isinstance(eid,str) or not eid or counts[eid]!=1 or eid not in permitted or eid not in eligible:continue
        location=row.get('location') or {}
        if not isinstance(row.get('quote'),str):continue
        packet=visible_table_packet(row.get('tableData'),row['quote'])
        if not packet:continue
        if (any(not group[0].strip() for group in packet['groups'])
            or any(type(r[0]) is not int or not r[1].strip() for r in packet['rows'])
            or len({r[0] for r in packet['rows']})!=len(packet['rows'])):continue
        table={'evidenceId':eid,'groups':[g[0] for g in packet['groups']],
            'methods':[[r[0],r[1]] for r in packet['rows']]}
        if isinstance(row.get('sourceRef'),str):table['sourceRef']=row['sourceRef']
        if isinstance(location,dict) and location.get('tableColumnMappingUnverified') is True:
            table['columnMappingUnverified']=True
        tables.append(table)
    ids={table['evidenceId'] for table in tables}
    return deepcopy({'tables':tables,'allowedTablesByClaim':{
        key:list(dict.fromkeys(ref for ref in refs if ref in ids)) for key,refs in permissions.items()}})
