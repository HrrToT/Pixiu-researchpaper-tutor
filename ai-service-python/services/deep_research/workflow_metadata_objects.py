"""Version 8: direct canonical metadata objects, without inferred leaf repairs."""
from copy import deepcopy
import json

from services.deep_research.workflow_metadata_rows import COMMON, PHASE_COLUMNS, _json_copy

NAME = 'workflow_metadata_objects_v1'
POLICY = (
    'Output the complete named metadata object in workflow_metadata_objects_v1. '
    'baseline/training_data are reserved inputs, never component IDs. '
    'Components represent persistent model/data/optimizer state, not stateless software routines. '
    'Fixed images and camera partitions use training_data reads. baselineMode existing requires an '
    'available complete checkpoint in supplied materials; a paper reporting training does not prove '
    'checkpoint availability. Retain unresolved prerequisites; train mode needs its complete later initializer. '
    'Arms need distinct group IDs; sharing controls physical execution. Combine read-only measurements '
    'only with every input, output, parameter and ordering explicit. '
    'Use components and phases, never componentRows or phaseRows. Each component is '
    '{componentId,appliesTo,lifecycle}; lifecycle is {scope,createAfter,disposeAfter}. '
    'createAfter and phase.after are always arrays of exact declared phase IDs, never state IDs, including a singleton; '
    '[] means before the timeline. Each read is an OBJECT {state,selector} OR '
    '{phaseId,outputId,selector}, never a bare ID or tuple. Each phase has ONE '
    '{action,parameters} operation object with {name,type,value} parameter objects; names are unique '
    'and type is number or choice. Distinct operations need explicit phases, not concatenated names. '
    'Metric results are future outputs, never invented observed numbers or placeholder zeroes. '
    'Input table/string sharing is input-only; never copy its arrays/references into output. '
    'Keep every required state, phase, operation, output, dependency and finite budget; '
    'named fields do not authorize missing values, invented assets, or scientific approval.\n'
)


def complete_scaffolding(value):
    try: value = _json_copy(value)
    except (TypeError, ValueError, RecursionError, OverflowError): return False
    return (isinstance(value,dict) and set(value)=={*COMMON,'components','phases'}
        and isinstance(value['components'],list) and len(value['components'])<=128
        and isinstance(value['phases'],list) and 1<=len(value['phases'])<=128
        and all(isinstance(c,dict) and set(c)=={'componentId','appliesTo','lifecycle'} for c in value['components'])
        and all(isinstance(p,dict) and set(p)==set(PHASE_COLUMNS) for p in value['phases']))


def decode(value):
    if not complete_scaffolding(value): raise ValueError('Incomplete or unknown named metadata fields')
    # Invalid leaves stay invalid, for the existing validators/model to explain.
    return _json_copy(value)


def encode(value):
    return decode(value)


def descriptor():
    from services.deep_research.workflow_units import descriptor as unit_descriptor, META
    result = unit_descriptor(META,7)
    result['name'] = NAME
    return result


def _at(value,path):
    for part in path.split('/')[1:]: value = value[int(part)] if isinstance(value,list) else value[part]
    return deepcopy(value)


def field_feedback(value,aliases):
    value = decode(value)
    from services.deep_research.workflow_metadata_repair import stable_feedback
    result = stable_feedback(value,aliases)
    for issue in result['issues']:
        try:
            actual = _at(value,issue['path']); issue['actualPresent'] = True
            if len(json.dumps(actual,ensure_ascii=False).encode('utf8'))<=256: issue['actual'] = actual
            else: issue['actualInInvalidMetadata'] = issue['path']
        except (KeyError,IndexError,ValueError,TypeError): issue['actualPresent'] = False
        if issue['code']=='timeline.phase.budget':
            issue['expected'] = 'fit requires finite {unit,perExecution}; optimizer_steps/epochs integer >=0, not bool; wall_seconds finite >=0'
        elif issue['code']=='timeline.phase.nonfit_budget': issue['expected'] = 'null for non-fit; never relabel actual fitting to avoid its cap'
        elif issue['code']=='timeline.component.lifecycle':
            issue['expected'] = '{scope:per_repeat|per_frame,createAfter:[phaseId,...],disposeAfter:phaseId|null}; createAfter is an array, not a scalar'
    phases=value['phases']; ids=[p['phaseId'] for p in phases]
    if all(isinstance(pid,str) for pid in ids) and len(set(ids))==len(ids):
        positions={pid:i for i,pid in enumerate(ids)}
        for c in value['components']:
            life=c.get('lifecycle'); after=life.get('createAfter') if isinstance(life,dict) else None
            if not isinstance(after,list) or any(not isinstance(pid,str) or pid not in positions for pid in after): continue
            boundary=max((positions[pid] for pid in after),default=-1)
            for i,p in enumerate(phases):
                if i>boundary: continue
                reads=p['reads']; updates=p['updates']; paths=[]
                if isinstance(reads,list): paths += [f'/phases/{i}/reads/{j}' for j,x in enumerate(reads) if isinstance(x,dict) and x.get('state')==c['componentId']]
                if isinstance(updates,list): paths += [f'/phases/{i}/updates/{j}' for j,x in enumerate(updates) if x==c['componentId']]
                for path in paths:
                    result['issues'].append({'code':'metadata.lifecycle.before_creation','path':path,
                        'actual':_at(value,path),'componentId':deepcopy(c['componentId']),'createAfter':deepcopy(after),
                        'expected':'initialize before this use; createAfter is after the referenced phase'})
    result['issues'].sort(key=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    result['canonicalValuesPreserved'] = True  # Preservation is not correction/approval.
    return result
