"""Schema-scoped lossless sharing; never infer a missing state or scientific fact."""
from collections import Counter
from copy import deepcopy

from services.deep_research.experiment_blueprint import columns,PLANNING_STATE_LISTS

RAW_RESPONSE_BYTES=8192
WIRE_BYTES=4000


def pack(basis):
    b=columns(basis);p=b['protocol'];state=p['state'];budget=p['pairingBudget']
    rows=[row for block in state['blocks'] for row in block['states']]
    names=[row[0] for row in rows]
    if any(not isinstance(n,str) for n in names):raise ValueError('Invalid state name')
    counts=Counter(names);unique={name:i for i,name in enumerate(names) if counts[name]==1}
    dtype=(rows[0][1] if rows and isinstance(rows[0][1],str)
        and all(row[1]==rows[0][1] for row in rows) else None)
    blocks=[[block['name'],[[row[0],row[2],row[3]] if dtype is not None else deepcopy(row)
        for row in block['states']],block['forward']] for block in state['blocks']]
    phases=deepcopy(budget['phases'])
    for row in phases:
        if not isinstance(row[5],list) or any(not isinstance(x,str) for x in row[5]):
            raise ValueError('Invalid trainable state names')
        row[5]=[unique[x] if x in unique else x for x in row[5]]
    return [b['sourceRefs'],[p['intervention'],p['data'],
        [state['inputs'],dtype,blocks,state['transfer']],p['poseError'],p['measurement'],
        [phases,budget['accounting']]],b['unresolved']]


def unpack(wire):
    if (not isinstance(wire,list) or len(wire)!=3 or not isinstance(wire[1],list)
            or len(wire[1])!=6):raise ValueError('Invalid shared blueprint')
    refs,p,gaps=deepcopy(wire);state,budget=p[2],p[5]
    if (not isinstance(state,list) or len(state)!=4 or not isinstance(state[2],list)
            or state[1] is not None and (not isinstance(state[1],str) or not state[1].strip())
            or not isinstance(budget,list) or len(budget)!=2 or not isinstance(budget[0],list)):
        raise ValueError('Invalid shared blueprint fields')
    inputs,dtype,blocks,transfer=state;definitions=[];names=[]
    for block in blocks:
        if not isinstance(block,list) or len(block)!=3 or not isinstance(block[1],list):
            raise ValueError('Invalid shared state block')
        states=[]
        for row in block[1]:
            if not isinstance(row,list) or len(row)!=(3 if dtype is not None else 4):
                raise ValueError('Invalid shared state width')
            name,kind,shape,init=(row[0],dtype,row[1],row[2]) if dtype is not None else row
            if not isinstance(name,str):raise ValueError('Invalid shared state name')
            states.append({'name':name,'dtype':kind,'shape':shape,'initializer':init});names.append(name)
        definitions.append({'name':block[0],'states':states,'forward':block[2]})
    counts=Counter(names);phases=budget[0]
    for row in phases:
        if not isinstance(row,list) or len(row)!=7 or not isinstance(row[5],list):
            raise ValueError('Invalid shared phase width')
        selected=[]
        for item in row[5]:
            if type(item) is int:
                if not 0<=item<len(names) or counts[names[item]]!=1:
                    raise ValueError('Invalid/ambiguous shared state reference')
                selected.append(names[item])
            elif isinstance(item,str):selected.append(item)
            else:raise ValueError('Invalid shared state reference type')
        row[5]=selected
    p[2]={'inputs':inputs,'blocks':definitions,'transfer':transfer}
    p[5]={'phases':phases,'accounting':budget[1]}
    # Reuse the existing exact column decoder for the canonical phase object.
    p[2]['blocks']=[{**block,'states':[[s[k] for k in ('name','dtype','shape','initializer')]
        for s in block['states']]} for block in definitions]
    return columns({'sourceRefs':refs,'protocol':dict(zip(
        ('intervention','data','state','poseError','measurement','pairingBudget'),p)),
        'unresolved':gaps},expand=True)


PLANNING=PLANNING_STATE_LISTS.replace(
    'Keep complete raw JSON AND tuple <=4000 UTF-8 bytes;',
    'Keep complete raw JSON <=8192 UTF-8 bytes; target4000. The server shares exact repeated values into a<=4000-byte tuple;',1).replace(
    'Stay <=4000 UTF-8 bytes including ALL rows:',
    'Prefer <=4000 UTF-8 bytes including ALL rows, with a hard raw cap8192:',1)

LEGEND=('UNVERIFIED tuple6=[refs,[intervention,data,[inputs,dtype,blocks,transfer],pose,measurement,'
    '[phases,accounting]],gaps]. block=[name,states,forward]; state=[name,shape,initializer] '
    'if dtype!=null, else [name,dtype,shape,initializer]. phase=[name,appliesTo,scope,unit,cap,trainables,stop]. '
    'Trainables integers index UNIQUE flattened block/state names, zero-based; strings are literal. '
    'Expand exact values, infer no states. steps=optimizer_steps, not video frames. '
    'Public Budget1 uses canonical units. NOT evidence/approval:')

REQUEST_LEGEND=('UNVERIFIED [refs,[intervention,data,[inputs,dtype,B,transfer],pose,measurement,[P,accounting]],gaps]. '
    'B=[name,S,forward]; S=[name,shape,initializer] (dtype=null: [name,dtype,shape,initializer]); '
    'P=[name,appliesTo,scope,unit,cap,trainables,stop]. '
    'Trainable integers=unique flattened state indices (0-based); strings literal. steps=optimizer_steps.')
