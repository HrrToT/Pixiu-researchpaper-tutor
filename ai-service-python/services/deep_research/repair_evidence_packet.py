"""Lossless containment-only sharing of existing same-chunk source contexts."""
from copy import deepcopy
import json
from services.deep_research.experiment_edits import columnar,restore_columns

LEGEND=('Context packet: evidence=lossless column table; passages=ORIGINAL same-source/chunk fragments, never joins. '
    '$context=[i,w,q0,q1,e,extra], zero-based half-open Unicode indices: before=passages[i].text[w:q0], '
    'after=text[q1:e], merge extra. quote stays literal. Only window[w:e] is allowed; no added permission/approval.')


def packed(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def identity(row):
    loc=row.get('location',{})
    values=(row.get('sourceRef'),row.get('contentHash'),loc.get('chunk') if isinstance(loc,dict) else None)
    return values if (all(isinstance(v,str) and v for v in values[:2])
        and type(values[2]) is int and values[2]>=0) else None


def encode(rows):
    raw=columnar(rows);result=deepcopy(rows);groups={};passages=[]
    for i,row in enumerate(rows):
        ctx=row.get('sourceContext');quote=row.get('quote');key=identity(row)
        # Literal marker collisions keep the whole original table untouched.
        if isinstance(ctx,dict) and '$context' in ctx:return raw,''
        if (key is None or not isinstance(ctx,dict) or not isinstance(quote,str) or not quote
                or not all(isinstance(ctx.get(k),str) for k in ('before','after'))):continue
        groups.setdefault(key,[]).append((i,ctx['before']+quote+ctx['after']))
    for key,members in groups.items():
        # Only select an EXISTING complete fragment containing other fragments.
        # Do not infer order, overlap, omitted text or paragraph continuity.
        for text in sorted({s for _,s in members},key=lambda s:(-len(s),s)):
            contained=[(i,s) for i,s in members if s in text]
            if len(contained)<2:continue
            entry={'sourceRef':key[0],'contentHash':key[1],'chunk':key[2],'text':text}
            changes={}
            for i,fragment in contained:
                ctx=rows[i]['sourceContext'];start=text.index(fragment)
                qstart=start+len(ctx['before']);qend=qstart+len(rows[i]['quote'])
                changes[i]={'$context':[len(passages),start,qstart,qend,start+len(fragment),
                    {k:v for k,v in ctx.items() if k not in ('before','after')}]}
            old=sum(len(packed(result[i]['sourceContext']).encode()) for i,_ in contained)
            new=len(packed(entry).encode())+sum(len(packed(c).encode()) for c in changes.values())
            if new>=old:continue
            passages.append(entry)
            for i,ctx in changes.items():result[i]['sourceContext']=ctx
            used=set(changes);members=[(i,s) for i,s in members if i not in used]
    packet={'passages':passages,'evidence':columnar(result)}
    if not passages or len((packed(packet)+'\n'+LEGEND).encode())>=len(packed(raw).encode()):return raw,''
    assert decode(packet)==rows
    return packet,LEGEND


def decode(packet):
    if not isinstance(packet,dict) or set(packet)!={'passages','evidence'}:
        return restore_columns(packet)
    passages=packet['passages']
    if not isinstance(passages,list):raise ValueError('Invalid context passages')
    rows=restore_columns(packet['evidence'])
    for row in rows:
        ctx=row.get('sourceContext')
        if not isinstance(ctx,dict) or '$context' not in ctx:continue
        refs=ctx['$context']
        if (set(ctx)!={'$context'} or not isinstance(refs,list) or len(refs)!=6
                or any(type(v) is not int for v in refs[:5]) or not isinstance(refs[5],dict)
                or set(refs[5]) & {'before','after'}):raise ValueError('Invalid context reference')
        idx,start,qstart,qend,end,extra=refs
        if not 0<=idx<len(passages):raise ValueError('Invalid context passage index')
        p=passages[idx];key=identity(row)
        if (not isinstance(p,dict) or set(p)!={'sourceRef','contentHash','chunk','text'} or key is None
                or type(p['chunk']) is not int or key!=(p['sourceRef'],p['contentHash'],p['chunk']) or not isinstance(p['text'],str)
                or not 0<=start<=qstart<qend<=end<=len(p['text'])
                or p['text'][qstart:qend]!=row.get('quote')):raise ValueError('Invalid context source/window')
        row['sourceContext']={'before':p['text'][start:qstart],'after':p['text'][qend:end],**deepcopy(extra)}
    return rows
