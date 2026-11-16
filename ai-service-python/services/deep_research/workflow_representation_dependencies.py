"""V2 model-declared input edges and original-evidence closure.

No retrieval ranking, quote truncation, scientific approval, extra call or
execution. V1 declarations and requests retain their original grammar.
"""
from copy import deepcopy
import json

from services.deep_research.contracts import DeepResearchError, digest


def descriptor():
    from services.deep_research.workflow_representation import descriptor as original
    result = original(1)
    result['name'] = 'workflow_representation_v2'
    schema = result['schema']
    text = {'type':'string', 'minLength':1, 'pattern':r'\S'}
    def obj(props):
        return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    def strings(**kw):
        return {'type':'array','items':deepcopy(text),'uniqueItems':True,'maxItems':128,**kw}
    selector = obj({'entity':deepcopy(text),'fields':strings(minItems=1),'axes':strings(maxItems=16)})
    source = {'anyOf': [obj({'state':deepcopy(text),'selector':deepcopy(selector)}),
        obj({'phaseId':deepcopy(text),'outputId':deepcopy(text),'selector':deepcopy(selector)})]}
    target = schema['properties']['targets']['items']
    target['properties']['inputDependencies'] = {'type':'array','maxItems':16,'items':obj({
        'input':source,'origin':{'enum':['paper','proposal']},'sourceRefs':strings()})}
    target['required'].append('inputDependencies')
    result['schema'] = compact_schema(schema)
    return result


def compact_schema(schema):
    """Share identical schema nodes, with an exact expansion check."""
    text = {'type':'string', 'minLength':1, 'pattern':r'\S'}
    # Share only identical schema objects. No original value/constraint removed.
    def share(value):
        if value == text:return {'$ref':'#/$defs/t'}
        if isinstance(value,dict):return {k:share(v) for k,v in value.items()}
        if isinstance(value,list):return [share(v) for v in value]
        return deepcopy(value)
    shared = share(schema)
    shared['$defs'] = {'t':deepcopy(text)}
    # Reuse repeated grammar objects; this never encodes source/model values.
    before=deepcopy(shared);counts={};objects={}
    def collect(value):
        if isinstance(value,dict):
            key=json.dumps(value,sort_keys=True,separators=(',',':'))
            counts[key]=counts.get(key,0)+1;objects[key]=value
            for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    collect({k:v for k,v in before.items() if k != '$defs'})
    def schema_node(value):
        return (isinstance(value.get('type'),str) or isinstance(value.get('anyOf'),list)
                or isinstance(value.get('enum'),list) or 'const' in value)
    repeated={k:'d'+str(i) for i,k in enumerate(sorted(k for k,n in counts.items()
        if n>1 and len(k)>40 and schema_node(objects[k])))}
    def compress(value,own=None):
        if isinstance(value,dict):
            key=json.dumps(value,sort_keys=True,separators=(',',':'))
            if key in repeated and key != own:return {'$ref':'#/$defs/'+repeated[key]}
            return {k:compress(v) for k,v in value.items()}
        if isinstance(value,list):return [compress(v) for v in value]
        return deepcopy(value)
    shared=compress({k:v for k,v in before.items() if k != '$defs'})
    shared['$defs']={**before['$defs'],**{name:compress(objects[k],k) for k,name in repeated.items()}}
    if expand_schema(shared) != expand_schema(before):
        raise ValueError('Representation schema sharing changed constraints')
    return shared


def expand_schema(schema):
    definitions=schema['$defs']
    def expand(value,visiting=()):
        if isinstance(value,dict):
            if set(value)=={'$ref'}:
                key=value['$ref'].removeprefix('#/$defs/')
                if key in visiting:raise ValueError('Cyclic local schema reference')
                return expand(definitions[key],(*visiting,key))
            return {k:expand(v,visiting) for k,v in value.items() if k != '$defs'}
        if isinstance(value,list):return [expand(v,visiting) for v in value]
        return deepcopy(value)
    return expand(schema)


def _dimension_matches(dimension, source):
    selector = source['selector']
    keys = ('state',) if 'state' in dimension else ('phaseId','outputId')
    return (all(source.get(k) == dimension[k] for k in keys)
        and selector['entity'] == dimension['entity'] and selector['fields'] == dimension['fields']
        and dimension['axis'] in selector['axes'])


def issues(value, metadata):
    """Explicit input coverage and lifecycle availability; not fact entailment."""
    from services.deep_research.workflow_initialization_context import _availability
    result = []
    components = metadata['components']
    phases = {p['phaseId']:p for p in metadata['phases']}
    for i,target in enumerate(value['targets']):
        path = f'/targets/{i}/inputDependencies'
        deps = target['inputDependencies']
        identities = [digest(d['input']) for d in deps]
        if len(set(identities)) != len(identities):
            result.append({'code':'representation.duplicate_dependency','path':path})
        name = target['target']
        if name == 'baseline':
            available_states, available_phases = {'training_data'}, set()
        else:
            candidates = [j for j,c in enumerate(components) if c['componentId'] == name]
            if len(candidates) != 1:continue  # Exact target coverage is diagnosed by the base contract.
            index = candidates[0]
            available, earlier = _availability(metadata, components[index], components[:index])
            available_states = {'training_data','baseline', *[c['componentId'] for c in earlier]}
            available_phases = {p['phaseId'] for p in available}
        for j,dependency in enumerate(deps):
            source = dependency['input']
            if 'state' in source:
                valid = source['state'] in available_states
            else:
                phase = phases.get(source['phaseId'])
                valid = (source['phaseId'] in available_phases and phase is not None
                         and source['outputId'] in phase['outputs'])
            if not valid:
                result.append({'code':'representation.unavailable_dependency','path':path+f'/{j}/input'})
        for j,state in enumerate(target['states']):
            for k,dimension in enumerate(state['shape']):
                if not isinstance(dimension,dict):continue
                matches = [d for d in deps if _dimension_matches(dimension,d['input'])]
                if len(matches) != 1:
                    result.append({'code':'representation.dimension_dependency',
                                   'path':f'/targets/{i}/states/{j}/shape/{k}'})
    return result


def constrain_initialization(result, target):
    """Constrain returned values, never populate a missing input or tensor."""
    sources = [deepcopy(d['input']) for d in target['inputDependencies']]
    mode = 'derive' if sources else 'fresh'
    schema = result['schema']
    branches = schema['$defs']['initialization']['anyOf']
    branch = next(b for b in branches if b['properties']['initializationMode']['const'] == mode)
    schema['$defs']['initialization']['anyOf'] = [branch]
    properties = branch['properties']
    if sources:
        properties['input'] = {'const':sources[0]}
        properties['additionalInputs'] = {'const':sources[1:]}
    for declared,state in zip(target['states'],properties['stateDefinitions']['prefixItems']):
        dimensions=[]
        for dimension in declared['shape']:
            if type(dimension) is int:dimensions.append({'const':dimension})
            else:
                index = next(i for i,s in enumerate(sources) if _dimension_matches(dimension,s))
                dimensions.append({'const':{'inputIndex':index,'axis':sources[index]['selector']['axes'].index(dimension['axis'])}})
        state['properties']['shape'] = {'type':'array',**({'prefixItems':dimensions} if dimensions else {}),
                                       'minItems':len(dimensions),'maxItems':len(dimensions)}
    # Remove unreachable grammar definitions after binding the exact input list.
    definitions=schema['$defs'];reached=set()
    def visit(value):
        if isinstance(value,dict):
            if '$ref' in value:
                key=value['$ref'].removeprefix('#/$defs/')
                if key not in reached:reached.add(key);visit(definitions[key])
            for k,v in value.items():
                if k != '$defs':visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(schema)
    schema['$defs'] = {k:v for k,v in definitions.items() if k in reached}


def initialization_issues(target, initialization):
    from services.deep_research.workflow_initialization_structured import selection
    actual=[]
    for source in initialization['inputs']:
        if not isinstance(source,dict):return [{'code':'representation.inputs_changed','path':'/initialization/inputs'}]
        actual.append({**source,'selector':selection(source.get('selector'))})
    expected=[d['input'] for d in target['inputDependencies']]
    mode='derive' if expected else 'fresh'
    return ([] if actual == expected and initialization.get('initializationMode') == mode else
            [{'code':'representation.inputs_changed','path':'/initialization/inputs'}])


def closure(record, target):
    """Declared type/input refs plus provenance of states already initialized.

    Phase dependencies follow the full metadata read/update graph. Missing or
    cyclic declarations fail before sending. Required global premises are added
    by the allocator independently, never replaced by model-authored references.
    """
    from services.deep_research.workflow_representation_stage import bound
    from services.deep_research.workflow_representation import verify
    from services.deep_research.workflow_premises import _refs
    frozen,metadata,aliases=bound(record,target)
    if frozen['version'] not in (2, 3):raise ValueError('Explicit dependencies require representation v2 or v3')
    value=verify(frozen,metadata,aliases)
    targets={t['target']:t for t in value['targets']}
    conventions={c['name']:c for c in value['conventions']}
    phases={p['phaseId']:p for p in metadata['phases']}
    blueprint=record['state']['executionWorkflowBlueprint']
    refs=set();done=set();visiting=set();phase_done=set();phase_visiting=set();parents=[]
    def prior(name):
        if name == target:return
        key='baseline' if name == 'baseline' else 'component:'+str(next(i for i,c in enumerate(metadata['components']) if c['componentId']==name))
        unit=blueprint['units'].get(key)
        if not isinstance(unit,dict):raise ValueError('Required prior initialization missing')
        if unit.get('status') == 'ready':parent=unit
        else:
            repair=blueprint.get('initializationRepair',{})
            if unit.get('status') != 'invalid_response' or repair.get('unitKey') != key or repair.get('status') != 'ready':
                raise ValueError('Required prior initialization not ready')
            parent=repair
        if digest(parent.get('value')) != parent.get('valueDigest'):
            raise ValueError('Required prior initialization changed')
        refs.update(_refs(parent['value']['sourceRefs']))
        audit=unit.get('premiseAllocation',{})
        refs.update(_refs(audit.get('requiredAliases',[])))
        parents.append({'unitKey':key,'valueDigest':parent['valueDigest']})
    def state(name):
        if name == 'training_data':return
        if name == 'baseline' and metadata['baselineMode']=='existing':
            refs.update(_refs(metadata['sourceRefs']));return
        if name not in targets:raise ValueError('Unknown dependency state')
        visit(name)
    def phase(identity):
        if identity in phase_visiting:raise ValueError('Cyclic phase dependency')
        if identity in phase_done:return
        if identity not in phases:raise ValueError('Unknown dependency phase')
        phase_visiting.add(identity);p=phases[identity]
        for name in p['updates']:state(name)
        for source in p['reads']:
            if 'state' in source:state(source['state'])
            else:phase(source['phaseId'])
        phase_visiting.remove(identity);phase_done.add(identity)
    def visit(name):
        if name in visiting:raise ValueError('Cyclic state dependency')
        if name in done:return
        visiting.add(name);declaration=targets[name]
        for state_type in declaration['states']:
            refs.update(_refs(state_type['sourceRefs']))
            for cid in state_type['conventionRefs']:refs.update(_refs(conventions[cid]['sourceRefs']))
        for dependency in declaration['inputDependencies']:
            refs.update(_refs(dependency['sourceRefs']));source=dependency['input']
            if 'state' in source:state(source['state'])
            else:phase(source['phaseId'])
        prior(name);visiting.remove(name);done.add(name)
    visit(target)
    if not refs <= set(aliases):raise ValueError('Dependency references outside original evidence scope')
    return {'requiredAliases':sorted(refs),'dependencyTargets':sorted(done),
        'dependencyPhases':sorted(phase_done),'priorInitializations':parents,
        'declarationDigest':frozen['valueDigest'],'scientificApproval':False}


def allocate(record, *, source_data, context, aliases, prior_values, node, render, transport_options=None):
    from services.deep_research.workflow_representation_stage import OPTION
    from services.deep_research.workflow_premises import required
    from services.deep_research.planning_transport import overhead_bytes
    from services.deep_research.workflow_metadata_window import input_limit
    target=(transport_options or {}).get(OPTION)
    try:
        dependency=closure(record,target)
        needed=required(record) | set(dependency['requiredAliases'])
        data=json.loads(source_data);rows=data['evidence']
        ids=[r['evidenceId'] for r in rows]
        if (len(set(ids))!=len(ids) or not set(ids)<=set(aliases) or not needed<=set(ids)):
            raise ValueError('Original required evidence missing')
    except (KeyError,TypeError,ValueError) as exc:
        raise DeepResearchError('invalid_workflow_premise_state','初始化依赖或所需原文缺失，不能发送。') from exc
    scoped=deepcopy(data);scoped['evidence']=[r for r in rows if r['evidenceId'] in needed]
    scoped['availableOriginalEvidenceAliases']=[r for r in ids if r in needed]
    ctx=deepcopy(context)
    if 'allowedSourceRefs' in ctx:
        if set(ctx['allowedSourceRefs'])!=set(aliases):raise ValueError('Input evidence permissions changed')
        ctx['allowedSourceRefs']=[r for r in ids if r in needed]
    text=json.dumps(scoped,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    body=render(text,ctx);overhead=overhead_bytes(record,node,transport_options)
    audit={'version':2,'node':node,'parentDataDigest':digest(data),'originalContextDigest':digest(context),
        **dependency,'requiredAliases':[r for r in ids if r in needed],'suppliedAliases':[r for r in ids if r in needed],
        'globalPremiseAliases':sorted(required(record)),'inputBytes':len(body.encode('utf8'))+overhead,
        'transportOverheadBytes':overhead,'maxInputBytes':input_limit(record,node),
        'sourceSelectionIsScientificApproval':False}
    return body,text,ctx,{k:aliases[k] for k in aliases if k in needed},audit
