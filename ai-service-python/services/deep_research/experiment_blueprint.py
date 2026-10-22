"""Private execution decisions, never source evidence or scientific approval."""
import math
from copy import deepcopy


def enabled(record):
    return (type(record.get('experimentPlanEncodingContractVersion')) is int
        and record['experimentPlanEncodingContractVersion'] in (3,4)
        and type(record.get('experimentDraftContractVersion')) is int
        and record['experimentDraftContractVersion']==6)


def _text(value):
    return isinstance(value,str) and bool(value.strip())


def _unique(rows,key):
    return len({r[key] for r in rows})==len(rows)


def valid_state(value):
    if (not isinstance(value,dict) or set(value)!={'inputs','blocks','transfer'}
            or not _text(value['inputs']) or not _text(value['transfer'])
            or not isinstance(value['blocks'],list) or not 1<=len(value['blocks'])<=16):
        return False
    for block in value['blocks']:
        if (not isinstance(block,dict) or set(block)!={'name','states','forward'}
                or not _text(block['name']) or not _text(block['forward'])
                or not isinstance(block['states'],list) or not 1<=len(block['states'])<=128):
            return False
        for state in block['states']:
            if (not isinstance(state,dict) or set(state)!={'name','dtype','shape','initializer'}
                    or any(not _text(state[k]) for k in ('name','dtype','initializer'))
                    or not isinstance(state['shape'],list) or len(state['shape'])>16
                    or any(not (type(d) is int and d>0 or _text(d)) for d in state['shape'])):
                return False
        if not _unique(block['states'],'name'):
            return False
    return _unique(value['blocks'],'name')


def valid_budget(value):
    if (not isinstance(value,dict) or set(value)!={'phases','accounting'}
            or not _text(value['accounting']) or not isinstance(value['phases'],list)
            or not 1<=len(value['phases'])<=16):
        return False
    for phase in value['phases']:
        if (not isinstance(phase,dict)
                or set(phase)!={'name','appliesTo','scope','unit','cap','trainables','stop'}
                or any(not _text(phase[k]) for k in ('name','scope','trainables','stop'))
                or phase['unit'] not in ('optimizer_steps','epochs','wall_seconds')
                or type(phase['cap']) not in (int,float) or phase['cap']<0):
            return False
        try:
            if not math.isfinite(phase['cap']):return False
        except OverflowError:
            return False
        if phase['unit']!='wall_seconds' and type(phase['cap']) is not int:
            return False
        groups=phase['appliesTo']
        if (not isinstance(groups,list) or not groups or any(not _text(g) for g in groups)
                or len(set(groups))!=len(groups)
                or any(g!='shared' and set(g)-{'0','1'} for g in groups)
                or 'shared' in groups and len(groups)!=1):
            return False
    return _unique(value['phases'],'name')


PLANNING = '''Plan an UNEXECUTED experiment before its full configuration. Return exactly:
{"sourceRefs":["supplied E IDs"],"protocol":{
"intervention":"actual method operation, control/treatment and insertion point",
"data":"evidenced dataset/member; proposed window/view split; training-only eligibility",
"state":{"inputs":"actual training inputs, axes, units and coordinate normalization",
"blocks":[{"name":"actual representation/module","states":[
{"name":"actual tensor/table name","dtype":"concrete dtype","shape":["explicit dimensions or declared input-dependent rules"],
"initializer":"actual values/distribution/RNG/seed or explicit input transform"}],
"forward":"actual input->operations->output, layers/activations and selectors"}],
"transfer":"what is fitted/shared/copied per frame/group; what never carries forward"},
"poseError":"requested perturbation or explicitly not applicable",
"measurement":"paired observables, references/ranges, units, aggregation, bytes and timing",
"pairingBudget":{"phases":[{"name":"unique fitting phase","appliesTo":["shared OR binary group IDs"],
"scope":"per-reference/per-frame/per-window, with finite repetition count/rule",
"unit":"optimizer_steps|epochs|wall_seconds","cap":0,"trainables":"actual fitted states",
"stop":"concrete stop rule; no final evaluation selection"}],
"accounting":"aggregate preparation/recovery caps and unit conversion; match whole-group effort for isolated effects"}},
"unresolved":["actual remaining evidence gap"]}.
This is a schema, not values to copy. Keep complete raw JSON AND tuple <=4000 UTF-8 bytes;
prefer concise English. Use 1..16 actual blocks/phases and named states, not narrative placeholders.
Each MLP affine layer has its own weight matrix [out,in] and optional bias vector, with
explicit activation/order; a dimensions list is NOT one weights tensor. Name hash/embedding
tables and their actual capacity/features/coordinate inputs when that method needs them.
Initialization operation and actual states must agree: scene-bound or nearest-neighbor
claims need declared transforms/inputs, not unrelated fixed constants. Declare proposed choices.
List EVERY fitting phase and finite temporal scope: reference training, learned field,
intervention/recovery. Name exact trainable states. Caps are finite nonnegative, steps/epochs
integer; zero means skipped fitting. No epoch=step assumption or reused undivided cap.
Use a common accounting unit or explicit conversion; if step conversion needs unavailable
minibatch counts, choose finite wall-time caps plus the required method schedule instead.
Budget1 public fields remain baseline/recovery only: detailed phases belong in its prose,
not new schema keys. Shared preparation must cover all its phases, with frame/window scope.
Keep proposed settings distinct from actual paper/data facts; own supplied E refs are still
required for every final attributed clause. Preserve method/modules, complete objective,
held-out isolation and honest whole-stage vs isolated-effect scope. No results/guarantees.
This private blueprint is unverified, not source evidence or permission. Missing source facts
remain exact gaps; do not invent a member/asset, omit a required module or weaken the task.
'''

LEGEND = ('Unverified tuple3=[sourceRefs,[intervention,data,state,poseError,measurement,pairingBudget],unresolved]; '
    'state blocks explicitly list tensor/table layouts, initialization and forward/transfer rules; '
    'pairingBudget phases explicitly list scope/unit/cap/trainables. NOT evidence or approval:')

STATE_COLUMNS=('name','dtype','shape','initializer')
PHASE_COLUMNS=('name','appliesTo','scope','unit','cap','trainables','stop')


def _rows(value,columns,*,expand):
    if not isinstance(value,list):raise ValueError('Invalid blueprint rows')
    result=[]
    for row in value:
        if expand:
            if not isinstance(row,list) or len(row)!=len(columns):raise ValueError('Invalid blueprint row width')
            result.append(dict(zip(columns,deepcopy(row))))
        else:
            if not isinstance(row,dict) or set(row)!=set(columns):raise ValueError('Invalid blueprint columns')
            result.append([deepcopy(row[k]) for k in columns])
    return result


def columns(basis,*,expand=False):
    """Change declared record representation only; no aliases, values or omissions inferred."""
    if (not isinstance(basis,dict) or set(basis)!={'sourceRefs','protocol','unresolved'}
            or not isinstance(basis['protocol'],dict)
            or set(basis['protocol'])!={'intervention','data','state','poseError','measurement','pairingBudget'}):
        raise ValueError('Invalid blueprint object')
    b=deepcopy(basis);p=b['protocol'];state=p['state'];budget=p['pairingBudget']
    if (not isinstance(state,dict) or set(state)!={'inputs','blocks','transfer'}
            or not isinstance(state['blocks'],list) or not isinstance(budget,dict)
            or set(budget)!={'phases','accounting'}):raise ValueError('Invalid blueprint fields')
    for block in state['blocks']:
        if not isinstance(block,dict) or set(block)!={'name','states','forward'}:raise ValueError('Invalid blueprint block')
        block['states']=_rows(block['states'],STATE_COLUMNS,expand=expand)
    budget['phases']=_rows(budget['phases'],PHASE_COLUMNS,expand=expand)
    return b


PLANNING_ROWS=PLANNING.replace(
    '{"name":"actual tensor/table name","dtype":"concrete dtype","shape":["explicit dimensions or declared input-dependent rules"],\n'
    '"initializer":"actual values/distribution/RNG/seed or explicit input transform"}',
    '["actual tensor/table name","concrete dtype",["explicit dimensions or declared input-dependent rules"],'
    '"actual initializer/RNG/seed or explicit input transform"]',1).replace(
    '{"name":"unique fitting phase","appliesTo":["shared OR binary group IDs"],\n'
    '"scope":"per-reference/per-frame/per-window, with finite repetition count/rule",\n'
    '"unit":"optimizer_steps|epochs|wall_seconds","cap":0,"trainables":"actual fitted states",\n'
    '"stop":"concrete stop rule; no final evaluation selection"}',
    '["unique fitting phase",["shared OR binary group IDs"],"finite repetition and temporal scope",'
    '"optimizer_steps|epochs|wall_seconds",0,"actual fitted states","concrete stopping rule"]',1)+'''
Use EXACT fixed rows: states=[name,dtype,shape,initializer] (4 columns);
phases=[name,appliesTo,scope,unit,cap,trainables,stop] (7 columns). No object rows.
sourceRefs may contain ONLY supplied E aliases; NEVER P/T/Q metadata IDs.
appliesTo uses ["shared"] for shared preparation, or actual binary group IDs
(single toggle: control="0", treatment="1"); never the labels "control"/"treatment".
measurement is ONE concise string, not a metric object. unresolved is TOP-LEVEL,
alongside sourceRefs and protocol, never inside protocol. Copy exact field nesting.
Stay <=4000 UTF-8 bytes including ALL rows: eliminate repeated narration of paper
facts/actions already defined, not required states, phases, inputs, choices or gaps.
'''

LEGEND_ROWS=('Unverified tuple4=[sourceRefs,[intervention,data,state,poseError,measurement,pairingBudget],unresolved]; '
    'state.blocks[].states columns=[name,dtype,shape,initializer]; '
    'pairingBudget.phases columns=[name,appliesTo,scope,unit,cap,trainables,stop]. '
    'Expand exact rows, no inferred values. NOT evidence or approval:')
