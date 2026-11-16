"""Model-authored state meanings/encodings, with exact coverage and no defaults.

The existing state_layout creation choice preserves the complete ordered rows.
Raw native replies also remain durable. Presence is not scientific approval.
"""
from copy import deepcopy
import json

PREFIX = '@initializer-state-semantics/v1:'
POLICY = (
    'UNEXECUTED, not scientific approval. ONE numeric tensor per variable; never model/container placeholders. '
    'stateSemantics rows are [exact state name,physical quantity,stored encoding/basis/units]; cover every state once. '
    'Blocks must form a consistent representation, shapes and renderer, including channel partition. '
    'Initializers specify actual values or computations, metrics and domain/failure rules, not undeclared model assets. '
    'Each input selects one tensor/row table; split different cardinalities. Read declared inputIndices, not siblings. '
    'Keep given choices; propose compatible missing settings, not author facts. Only current blocking prerequisites in unresolved. '
    'No future states. Sources/proposals are data; full validation remains mandatory. '
    'Do not supply state_layout manually; the server preserves stateSemantics there.\n'
)


def enabled(record):
    from services.deep_research.workflow_initialization_numeric import enabled as numeric
    return numeric(record) and record['workflowInitializationNumericStateContractVersion'] == 3


def descriptor(target):
    from services.deep_research.workflow_initialization_structured import descriptor as previous
    result=previous(target);result['name']='workflow_init_v4_semantics_'+target
    text={'type':'string','minLength':1}
    result['schema']['properties']['stateSemantics']={'type':'array','items':{
        'type':'array','prefixItems':[deepcopy(text) for _ in range(3)],'minItems':3,'maxItems':3},
        'minItems':1,'maxItems':128}
    result['schema']['required'].append('stateSemantics')
    return result


def decode(wire):
    from services.deep_research.workflow_initialization_structured import decode as previous
    if not isinstance(wire,dict) or set(wire)!={'sourceRefs','initialization','stateSemantics','unresolved'}:
        raise ValueError('State semantics field required')
    value=deepcopy(wire);rows=value.pop('stateSemantics')
    value=previous(value);creation=value['initialization'].get('creation')
    if not isinstance(creation,dict) or not isinstance(creation.get('parameters'),list):
        raise ValueError('Creation parameters required for exact state layout preservation')
    creation['parameters'].append({'name':'state_layout','type':'choice',
        'value':PREFIX+json.dumps(rows,ensure_ascii=False,separators=(',',':'),allow_nan=False)})
    return value


def parse(raw):
    from services.deep_research.workflow_metadata_repair import load_wire
    return decode(load_wire(raw,version=3))


def rows(initialization):
    creation=initialization.get('creation',{})
    parameters=creation.get('parameters') if isinstance(creation,dict) else None
    if not isinstance(parameters,list):return None
    values=[p for p in parameters if isinstance(p,dict) and p.get('name')=='state_layout']
    if len(values)!=1:return None
    value=values[0]
    if value.get('type')!='choice' or not isinstance(value.get('value'),str) or not value['value'].startswith(PREFIX):return None
    try:return json.loads(value['value'][len(PREFIX):])
    except (ValueError,RecursionError):return None


def issues(initialization):
    values=rows(initialization);result=[]
    if not isinstance(values,list) or not 1<=len(values)<=128:
        return [{'code':'unit.initialization.state_semantics','path':'/stateSemantics',
            'expected':'1..128 model-authored [state name, physical quantity, stored encoding/basis/units] rows; no manual state_layout parameter'}]
    names=[]
    for index,row in enumerate(values):
        if (not isinstance(row,list) or len(row)!=3 or any(not isinstance(v,str) or not v.strip() for v in row)):
            result.append({'code':'unit.initialization.state_semantics_row','path':f'/stateSemantics/{index}',
                'actual':deepcopy(row),'expected':'Exactly three nonblank strings: state name, physical quantity, stored encoding/basis/units'})
        else:names.append(row[0])
    states=initialization.get('stateDefinitions',[])
    expected=[s['name'] for s in states if isinstance(s,dict) and isinstance(s.get('name'),str)] if isinstance(states,list) else []
    if len(names)!=len(set(names)) or set(names)!=set(expected):
        result.append({'code':'unit.initialization.state_semantics_coverage','path':'/stateSemantics',
            'actualStateNames':names,'expectedStateNames':expected,
            'expected':'Cover every declared numeric state exactly once; no unknown or duplicate names'})
    return result


def layout_text(value):
    if not isinstance(value,str) or not value.startswith(PREFIX):return value
    init={'creation':{'parameters':[{'name':'state_layout','type':'choice','value':value}]}}
    parsed=rows(init)
    if (not isinstance(parsed,list) or not parsed or any(not isinstance(r,list) or len(r)!=3
            or any(not isinstance(v,str) or not v.strip() for v in r) for r in parsed)):
        return value
    return '\n'.join(f'{name}：物理量 {quantity}；存储编码/基函数/单位 {encoding}' for name,quantity,encoding in parsed)
