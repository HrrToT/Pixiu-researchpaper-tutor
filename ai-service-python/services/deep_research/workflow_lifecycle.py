"""Static prospective timeline checks. No allocation, execution or scientific approval."""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
import math

from services.deep_research.group_spec import validate_operation

SCOPES = ('per_repeat', 'per_frame')
PHASE_FIELDS = {'phaseId','scope','kind','groups','sharing','after','reads','updates','outputs','action','budget'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value, *, empty=True):
    return (isinstance(value, list) and (empty or bool(value))
            and all(_text(v) for v in value) and len(value) == len(set(value)))


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _creation_point(life, phase_map, frame_start):
    point=max((phase_map[p][0] for p in life['createAfter'] if p in phase_map),default=-1)+0.5
    return max(point,frame_start-0.5) if life['scope']=='per_frame' else point


def lifecycle_issues(spec):
    """Check only timeline/lifetimes; callers must also validate full workflow values."""
    issues=[]
    def fail(code, path): issues.append({'code':'timeline.'+code,'path':path})
    if not isinstance(spec, dict): return [{'code':'timeline.spec','path':''}]
    phases, components, frames = spec.get('phases'), spec.get('componentInitializations'), spec.get('frameIterations')
    if not isinstance(phases,list) or not 1 <= len(phases) <= 128:
        fail('phases','/phases'); return issues
    if not isinstance(components,list) or len(components)>128:
        fail('components','/componentInitializations'); return issues
    if type(frames) is not int or frames<0: fail('frameIterations','/frameIterations')
    phase_map={}; component_map={}
    for i,p in enumerate(phases):
        path=f'/phases/{i}'
        if (not isinstance(p,dict) or set(p)!=PHASE_FIELDS or not _text(p.get('phaseId'))
                or p['phaseId'] in phase_map):
            fail('phase.fields',path); continue
        phase_map[p['phaseId']]=(i,p)
        if p['scope'] not in SCOPES: fail('phase.scope',path+'/scope')
        if p['kind'] not in ('fit','setup','evaluate','record'): fail('phase.kind',path+'/kind')
        if p['sharing'] not in ('shared','per_group'): fail('phase.sharing',path+'/sharing')
        for field in ('groups','after','updates','outputs'):
            if not _strings(p[field],empty=field!='groups'): fail('phase.'+field,path+'/'+field)
        if p['kind'] in ('evaluate','record') and p['updates']:
            fail('phase.evaluation_updates',path+'/updates')
        if isinstance(p['updates'],list) and 'training_data' in p['updates']:
            fail('phase.data_mutation',path+'/updates')
        if not isinstance(p['reads'],list): fail('phase.reads',path+'/reads')
        try: bad=validate_operation(p['action'],'phase')
        except (TypeError,ValueError): bad=['invalid']
        if bad: fail('phase.action',path+'/action')
        budget=p['budget']
        if p['kind']=='fit':
            if (not isinstance(budget,dict) or set(budget)!={'unit','perExecution'}
                    or budget.get('unit') not in ('optimizer_steps','epochs','wall_seconds')
                    or not _finite(budget.get('perExecution')) or budget['perExecution']<0
                    or budget['unit']!='wall_seconds' and type(budget['perExecution']) is not int):
                fail('phase.budget',path+'/budget')
        elif budget is not None: fail('phase.nonfit_budget',path+'/budget')
    for i,c in enumerate(components):
        path=f'/componentInitializations/{i}'
        if (not isinstance(c,dict) or not _text(c.get('componentId'))
                or c['componentId'] in component_map or c['componentId'] in ('baseline','training_data')):
            fail('component.id',path); continue
        component_map[c['componentId']]=(i,c)
        if not _strings(c.get('appliesTo'),empty=False): fail('component.groups',path+'/appliesTo')
        if not isinstance(c.get('inputs'),list): fail('component.inputs',path+'/inputs')
        life=c.get('lifecycle')
        if (not isinstance(life,dict) or set(life)!={'scope','createAfter','disposeAfter'}
                or life.get('scope') not in SCOPES or not _strings(life.get('createAfter'))
                or life.get('disposeAfter') is not None and not _text(life['disposeAfter'])):
            fail('component.lifecycle',path+'/lifecycle')
    # Stop on malformed types before reference arithmetic or graph construction.
    if issues: return issues
    frame_indices=[i for i,p in enumerate(phases) if p['scope']=='per_frame']
    if bool(frame_indices)!=(frames>0): fail('frameIterations','/frameIterations')
    if frame_indices and frame_indices!=list(range(frame_indices[0],frame_indices[-1]+1)):
        fail('frame_block','/phases')
    frame_start=frame_indices[0] if frame_indices else 0
    events={}; edges=defaultdict(set); consumers=defaultdict(list); data_edges=defaultdict(set)
    def edge(a,b): edges[a].add(b)
    for i,p in enumerate(phases):
        node='phase:'+p['phaseId']; events[node]=(float(i),0,0)
        for j,ref in enumerate(p['after']):
            if ref not in phase_map: fail('phase.after_missing',f'/phases/{i}/after/{j}')
            else:
                if phase_map[ref][0]>=i: fail('phase.after_future',f'/phases/{i}/after/{j}')
                edge('phase:'+ref,node)
    creation={}; disposal={}
    for cid,(i,c) in component_map.items():
        life=c['lifecycle']; path=f'/componentInitializations/{i}/lifecycle'
        for j,ref in enumerate(life['createAfter']):
            if ref not in phase_map: fail('creation.phase_missing',path+f'/createAfter/{j}')
            else:
                pi,p=phase_map[ref]
                if life['scope']=='per_repeat' and p['scope']=='per_frame': fail('creation.scope',path)
                edge('phase:'+ref,'init:'+cid)
        point=_creation_point(life,phase_map,frame_start)
        if life['scope']=='per_frame':
            if not frame_indices or point>frame_indices[-1]: fail('creation.frame_position',path)
        creation[cid]=point; events['init:'+cid]=(point,int(life['scope']=='per_frame'),i+1)
        ref=life['disposeAfter']
        if life['scope']=='per_frame' and ref is None: fail('disposal.required',path+'/disposeAfter')
        if ref is not None:
            if ref not in phase_map: fail('disposal.phase_missing',path+'/disposeAfter')
            else:
                pi,p=phase_map[ref]; disposal[cid]=pi+0.25
                if p['scope']!=life['scope']: fail('disposal.scope',path+'/disposeAfter')
                if pi<point: fail('disposal.before_creation',path+'/disposeAfter')
                events['dispose:'+cid]=(pi+0.25,int(life['scope']=='per_frame'),i+1);edge('phase:'+ref,'dispose:'+cid)
    # The declared phase order and initialization boundaries establish an event order.
    ordered=sorted(events,key=events.get)
    for a,b in zip(ordered,ordered[1:]): edge(a,b)
    def read(item,*,target,point,scope,groups,path,component_index=None):
        if not isinstance(item,dict): fail('input.fields',path);return
        if set(item)=={'state','selector'} and all(_text(v) for v in item.values()):
            state=item['state']
            if state in ('baseline','training_data'): return
            if state not in component_map: fail('input.component_missing',path);return
            si,source=component_map[state]
            if component_index is not None and si>=component_index: fail('input.future_component',path)
            if events['init:'+state]>=events[target]: fail('input.before_creation',path)
            if source['lifecycle']['scope']=='per_frame' and scope=='per_repeat': fail('input.scope',path)
            if not set(groups)<=set(source['appliesTo']): fail('input.group_leak',path)
            if state in disposal and point>disposal[state]: fail('input.after_disposal',path)
            edge('init:'+state,target);consumers[state].append(target)
            data_edges['init:'+state].add(target)
        elif set(item)=={'phaseId','outputId','selector'} and all(_text(v) for v in item.values()):
            pid=item['phaseId']
            if pid not in phase_map: fail('input.phase_missing',path);return
            pi,source=phase_map[pid]
            if item['outputId'] not in source['outputs']: fail('input.output_missing',path)
            if pi>=point: fail('input.future_output',path)
            if source['scope']=='per_frame' and scope=='per_repeat': fail('input.scope',path)
            if not set(groups)<=set(source['groups']): fail('input.group_leak',path)
            edge('phase:'+pid,target);data_edges['phase:'+pid].add(target)
        else: fail('input.fields',path)
    for cid,(i,c) in component_map.items():
        for j,item in enumerate(c['inputs']):
            read(item,target='init:'+cid,point=creation[cid],scope=c['lifecycle']['scope'],groups=c['appliesTo'],
                 path=f'/componentInitializations/{i}/inputs/{j}',component_index=i)
    for i,p in enumerate(phases):
        for j,item in enumerate(p['reads']):
            read(item,target='phase:'+p['phaseId'],point=i,scope=p['scope'],groups=p['groups'],path=f'/phases/{i}/reads/{j}')
        for j,state in enumerate(p['updates']):
            # Validate the declared write target with the same lifetime and
            # group rules as a read. This reference is validation-only.
            read({'state':state,'selector':'declared update target'},target='phase:'+p['phaseId'],
                 point=i,scope=p['scope'],groups=p['groups'],path=f'/phases/{i}/updates/{j}')
    for cid,(i,c) in component_map.items():
        if not consumers[cid]: fail('component.unused',f'/componentInitializations/{i}')
        if cid in disposal:
            for consumer in consumers[cid]: edge(consumer,'dispose:'+cid)
    # Iterative topological check avoids recursion limits on bounded adversarial plans.
    indegree={n:0 for n in events}
    for a,targets in edges.items():
        for b in targets:
            if a in events and b in events: indegree[b]+=1
    pending=[n for n,d in indegree.items() if d==0];count=0
    while pending:
        node=pending.pop();count+=1
        for child in edges[node]:
            if child in indegree:
                indegree[child]-=1
                if indegree[child]==0:pending.append(child)
    if count!=len(events): fail('cycle','/phases')
    universe={g for p in phases for g in p['groups']}|{g for c in components for g in c['appliesTo']}
    for group in universe:
        fits=[i for i,p in enumerate(phases) if p['kind']=='fit' and group in p['groups']]
        evaluations=[(i,p) for i,p in enumerate(phases) if p['kind']=='evaluate' and group in p['groups']]
        if not evaluations: fail('evaluation.missing','/phases')
        for i,p in evaluations:
            if fits and i<=max(fits):fail('evaluation.before_fit_end',f'/phases/{i}')
        # Data flow, rather than mere temporal adjacency, must connect results to a record.
        reachable={'phase:'+p['phaseId'] for _,p in evaluations}; queue=list(reachable)
        while queue:
            node=queue.pop()
            for child in data_edges[node]:
                if child not in reachable: reachable.add(child);queue.append(child)
        if not any(p['kind']=='record' and group in p['groups'] and 'phase:'+p['phaseId'] in reachable for p in phases):
            fail('record.evaluation_missing','/phases')
    return issues


def lifecycle_errors(spec):
    return list(dict.fromkeys(i['code'] for i in lifecycle_issues(spec)))


def lifecycle_events(spec):
    """Ordered unexecuted template for display; per-frame events repeat together."""
    if lifecycle_errors(spec): return []
    phases=spec['phases']; phase_map={p['phaseId']:(i,p) for i,p in enumerate(phases)}
    frame_start=next((i for i,p in enumerate(phases) if p['scope']=='per_frame'),0)
    items=[]
    for i,p in enumerate(phases):
        items.append(((float(i),0,0),{'kind':'phase','id':p['phaseId'],'scope':p['scope'],'groups':p['groups']}))
    for i,c in enumerate(spec['componentInitializations']):
        life=c['lifecycle'];rank=int(life['scope']=='per_frame')
        common={'id':c['componentId'],'scope':life['scope'],'groups':c['appliesTo']}
        items.append(((_creation_point(life,phase_map,frame_start),rank,i+1),{**common,'kind':'initialize'}))
        if life['disposeAfter'] is not None:
            point=phase_map[life['disposeAfter']][0]+0.25
            items.append(((point,rank,i+1),{**common,'kind':'dispose'}))
    return [deepcopy(event) for _,event in sorted(items,key=lambda item:item[0])]


def lifecycle_budget_errors(spec, budget):
    """Per-repeat whole-group accounting, including every frame; no values are repaired."""
    from services.deep_research.budget_spec import validate_budget_spec
    if lifecycle_errors(spec): return ['timeline.invalid']
    try: bad=validate_budget_spec(budget)
    except (TypeError,ValueError,OverflowError): bad=['invalid']
    if bad: return ['timeline.budget.invalid']
    recovery=budget['recovery']; terms={g:Fraction(0) for g in recovery['groups']}; errors=[]
    for phase in spec['phases']:
        if not set(phase['groups'])<=set(terms): errors.append('timeline.budget.unknown_group')
        if phase['kind']!='fit': continue
        if phase['budget']['unit']!=recovery['unit']: errors.append('timeline.budget.unit')
        # Exact declared-decimal arithmetic: large integer counts and 0.1*3
        # must not be compared using rounded floats or a relative tolerance.
        amount=Fraction(str(phase['budget']['perExecution']))*(spec['frameIterations'] if phase['scope']=='per_frame' else 1)
        for group in phase['groups']:
            if group in terms: terms[group]+=amount
    for c in spec['componentInitializations']:
        if not set(c['appliesTo'])<=set(terms):errors.append('timeline.budget.unknown_group')
    for group,actual in terms.items():
        expected=recovery['groups'][group]
        if actual!=Fraction(str(expected)):errors.append('timeline.budget.group_total')
        if not any(p['kind']=='evaluate' and group in p['groups'] for p in spec['phases']):errors.append('timeline.budget.group_evaluation')
        if not any(p['kind']=='record' and group in p['groups'] for p in spec['phases']):errors.append('timeline.budget.group_record')
    return list(dict.fromkeys(errors))
