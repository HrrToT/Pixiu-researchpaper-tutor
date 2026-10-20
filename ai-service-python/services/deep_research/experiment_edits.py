"""Bounded experimental edits; expand to full claims before existing checks."""
from collections import Counter
from copy import deepcopy
import re

OUTPUT_TOKENS=4096
WRITABLE={'text','executionSpec','evidenceRefs','conditions','detailLevel','tableBindings'}


def columnar(rows):
    """Lossless JSON table: named common values, then an extra-fields object."""
    if not rows:return []
    keys=[key for key in rows[0] if all(key in row for row in rows)]
    return deepcopy({'columns':keys,'rows':[[*[row[k] for k in keys],
        {k:v for k,v in row.items() if k not in keys}] for row in rows]})


def restore_columns(table):
    if table==[]:return []
    keys=table['columns'];result=[]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate columns')
    for row in table['rows']:
        if len(row)!=len(keys)+1 or not isinstance(row[-1],dict) or set(keys)&set(row[-1]):
            raise ValueError('Invalid lossless row')
        result.append({**dict(zip(keys,deepcopy(row[:-1]))),**deepcopy(row[-1])})
    return result


def can_edit(report):
    from services.deep_research.experiment_repair import compatible
    typed={'groups','data','analysis','budget','hypothesis','controls','steps'}
    claims=report.get('claims',[])
    return bool(claims) and compatible(report) and all(
        c.get('kind') in {'proposal','suggestion','hypothesis'} and
        (c.get('designRole') not in typed or isinstance(c.get('executionSpec'),dict)) for c in claims)


def _parts(path):
    if not isinstance(path,str) or not path.startswith('/') or len(path)>1000:
        raise ValueError('Invalid pointer')
    raw=path[1:].split('/')
    if not 1<=len(raw)<=24 or any(re.search(r'~(?![01])',part) for part in raw):
        raise ValueError('Invalid pointer escapes')
    parts=[part.replace('~1','/').replace('~0','~') for part in raw]
    if parts[0] not in WRITABLE:raise ValueError('Immutable claim field')
    return parts


def _index(token,size,*,add=False):
    if add and token=='-':return size
    if not re.fullmatch(r'0|[1-9]\d*',token):raise ValueError('Invalid array index')
    index=int(token)
    if index<0 or index>size or (not add and index==size):
        raise ValueError('Array index out of range')
    return index


def _apply(row,edit):
    op=edit.get('op')
    if op not in {'replace','add','remove'} or set(edit)!=({'op','path'} if op=='remove' else {'op','path','value'}):
        raise ValueError('Invalid edit shape')
    parts=_parts(edit['path']);parent=row
    for part in parts[:-1]:
        if isinstance(parent,dict):parent=parent[part]
        elif isinstance(parent,list):parent=parent[_index(part,len(parent))]
        else:raise ValueError('Pointer traverses a scalar')
    key=parts[-1]
    if isinstance(parent,dict):
        if op in {'replace','remove'} and key not in parent:raise ValueError('Missing property')
        if op=='remove':del parent[key]
        else:parent[key]=deepcopy(edit['value'])
    elif isinstance(parent,list):
        index=_index(key,len(parent),add=op=='add')
        if op=='add':parent.insert(index,deepcopy(edit['value']))
        elif op=='remove':parent.pop(index)
        else:parent[index]=deepcopy(edit['value'])
    else:raise ValueError('Pointer parent is scalar')


def expand(prepared,response):
    """Invalid rows yield no revision. Permissions/roles are still checked later.

    The model never edits storage or verified claims. Each target expands from
    its exact original; the ordinary parser/normalizer and all independent
    structural/source/scientific checks receive complete reconstructed claims.
    """
    from services.deep_research.execution_materialization import verification_claim_view
    from services.deep_research.answer_constraints import resolve_evidence_aliases
    counts=Counter(r.get('claimId') for r in response if isinstance(r,dict) and isinstance(r.get('claimId'),str))
    result=[];reverse={eid:alias for alias,eid in prepared['aliases'].items()}
    for item in response:
        if not isinstance(item,dict) or set(item)!={'claimId','edits'}:continue
        cid=item['claimId'];edits=item['edits']
        if not isinstance(cid,str) or counts[cid]!=1 or cid not in prepared['originals']:continue
        if not isinstance(edits,list) or not 1<=len(edits)<=64:continue
        original=verification_claim_view(prepared['originals'][cid])
        base=resolve_evidence_aliases({'claims':[original]},reverse)['claims'][0]
        try:
            for edit in edits:
                if not isinstance(edit,dict):raise ValueError('Invalid edit')
                _apply(base,edit)
        except (ValueError,KeyError,IndexError,TypeError,OverflowError):
            continue
        result.append(base)
    return result
