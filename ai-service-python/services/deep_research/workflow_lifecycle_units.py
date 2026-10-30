"""Version 7 unit grammar and partial checks; never invent initialization values."""
from copy import deepcopy

from services.deep_research.workflow_lifecycle import lifecycle_issues


def unit_input_text(source_data,context):
    """Choose only a verified lossless input representation, with its full legend."""
    import json
    from services.deep_research.contracts import digest
    from services.deep_research.nested_tables import pack,unpack
    data={'authoritativeInput':json.loads(source_data),'unitContext':context}
    encode=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    wire=pack(data)
    if digest(unpack(wire))!=digest(data):raise ValueError('Unit input encoding is not lossless')
    legend=('\nInput encoding only: {"@":[columns,rows]} expands to an object list; '
        '{"!":object} escapes a literal @/! object. Expand exactly before reading every source and chosen value.\n')
    literal=encode(data);encoded=encode(wire)+legend
    return encoded if len(encoded.encode('utf8'))<len(literal.encode('utf8')) else literal


def extend_schema(full):
    """Change only a copied v4 grammar; frozen unit version 6 is unaffected."""
    full=deepcopy(full); defs=full['$defs']; text={'type':'string','minLength':1}
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    def arr(items,**kw):return {'type':'array','items':items,**kw}
    def ref(name):return {'$ref':'#/$defs/'+name}
    scope={'enum':['per_repeat','per_frame']}
    defs['timelineInput']={'anyOf':[obj({'state':text,'selector':text}),
        obj({'phaseId':text,'outputId':text,'selector':text})]}
    defs['lifecycle']=obj({'scope':scope,'createAfter':arr(text,uniqueItems=True),
        'disposeAfter':{'anyOf':[text,{'type':'null'}]}})
    defs['phase']=obj({'phaseId':text,'scope':scope,'kind':{'enum':['fit','setup','evaluate','record']},
        'groups':arr(text,minItems=1,uniqueItems=True),'sharing':{'enum':['shared','per_group']},
        'after':arr(text,uniqueItems=True),'reads':arr(ref('timelineInput')),
        'updates':arr(text,uniqueItems=True),'outputs':arr(text,uniqueItems=True),'action':ref('operation'),
        'budget':{'anyOf':[{'type':'null'},obj({'unit':{'enum':['optimizer_steps','epochs','wall_seconds']},
            'perExecution':{'type':'number','minimum':0}})]}})
    defs['initialization']['properties']['inputs']=arr(ref('timelineInput'))
    workflow=full['properties']['workflow']['properties']
    workflow['frameIterations']={'type':'integer','minimum':0}
    workflow['phases']=arr(ref('phase'),minItems=1,maxItems=128)
    return full


def timeline_spec(meta, *, earlier=(), target=None, initialization=None):
    """Partial view for validation only; placeholders never enter a request or assembly."""
    by_id={c['componentId']:c for c in earlier}
    components=[]
    for c in meta['components']:
        item=deepcopy(c);item['inputs']=deepcopy(by_id.get(c['componentId'],{}).get('inputs',[]))
        if target is not None and c['componentId']==target['componentId']:
            item['inputs']=deepcopy(initialization['inputs'])
        components.append(item)
    return {'frameIterations':meta['frameIterations'],'phases':deepcopy(meta['phases']),
            'componentInitializations':components}


def metadata_errors(meta):
    # Initializer-only edges are not yet selected. Defer their coverage/dataflow
    # checks to complete assembly; do not invent edges or approve the timeline.
    deferred={'timeline.component.unused','timeline.record.evaluation_missing'}
    return [i['code'] for i in lifecycle_issues(timeline_spec(meta)) if i['code'] not in deferred]


def initialization_errors(meta, target, initialization, earlier):
    if target is None:return []  # Baseline is a prelude, checked by the full-state validator.
    index=next(i for i,c in enumerate(meta['components']) if c['componentId']==target['componentId'])
    prefix=f'/componentInitializations/{index}/'
    issues=lifecycle_issues(timeline_spec(meta,earlier=earlier,target=target,initialization=initialization))
    return [i['code'] for i in issues if i['code']!='timeline.component.unused'
        and (i['path'].startswith(prefix) or i['code']=='timeline.cycle')]


META_POLICY=('Return sourceRefs,baselineMode,replicationMode,components,checkpointSelection,frameIterations,phases,unresolved. '
    'Components contain exactly componentId,appliesTo,lifecycle. Declare full phase actions, reads, updates, outputs, '
    'group coverage and fit caps, then create/dispose boundaries. Components are recipes, not allocated upfront. '
    'Declare components in initializer dependency order. Do not generate initial-state tensors here. '
    'Keep shared versus per-group execution explicit and count every frame in whole-group recovery budgets. '
    'All references use the exact declared IDs. Baseline training precedes this timeline. '
    'Record phases consume evaluation outputs; evaluation and record never update models. '
    'Preserved phase outputs may outlive freed components. Per-frame instances cannot leak into the next frame.')

INIT_POLICY=('For this ONE target, select the complete initial state at its declared creation boundary. '
    'For a component, inputs may be {state,selector} for available baseline/training_data/earlier components, '
    'or {phaseId,outputId,selector} for a declared output already produced before this creation boundary. '
    'A late-created component may derive from its preceding phase output; do not fabricate that state before fitting. '
    'Baseline initialization is always before timeline fitting and may use training_data only. '
    'Keep all real trainable and nontrainable initialization states; image counts are not point counts. '
    'Do not allocate guessed dimensions or omit required states to satisfy the response cap.')
