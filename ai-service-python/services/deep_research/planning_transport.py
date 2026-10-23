"""Frozen schema transport for new private plans, independent of source support."""
import json
from llm.responses_transport import API_KEY


def enabled(record,node):
    from services.deep_research.workflow_transport import enabled as workflow_enabled
    if workflow_enabled(record, node):
        return True
    return (node=='plan_experiment' and isinstance(record,dict)
        and type(record.get('structuredOutputContractVersion')) is int
        and record['structuredOutputContractVersion'] in (14,15))


def descriptor():
    text={'type':'string','minLength':1}
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    def array(items,**kw):return {'type':'array','items':items,**kw}
    state={'type':'array','prefixItems':[text,text,array({'anyOf':[
        {'type':'integer','minimum':1},text]},maxItems=16),text],'minItems':4,'maxItems':4}
    phase={'type':'array','prefixItems':[text,array(text,minItems=1,uniqueItems=True),text,
        {'type':'string','enum':['optimizer_steps','steps','epochs','wall_seconds']},
        {'type':'number','minimum':0},array(text,maxItems=128,uniqueItems=True),text],
        'minItems':7,'maxItems':7}
    schema=obj({'sourceRefs':array(text,maxItems=20,uniqueItems=True),
        'protocol':obj({'intervention':text,'data':text,
            'state':obj({'inputs':text,'blocks':array(obj({'name':text,'states':array(state,minItems=1,
                maxItems=128),'forward':text}),minItems=1,maxItems=16),'transfer':text}),
            'poseError':text,'measurement':text,
            'pairingBudget':obj({'phases':array(phase,minItems=1,maxItems=16),'accounting':text})}),
        'unresolved':array(text,maxItems=8)})
    return {'type':'json_schema','name':'private_experiment_columns_v1','schema':schema}


def descriptor_for(record, node):
    from services.deep_research.workflow_transport import enabled as workflow_enabled, descriptor as workflow_descriptor
    return workflow_descriptor(record['executionWorkflowContractVersion']) if workflow_enabled(record, node) else descriptor()


def options_for_record(record,node,options):
    """Own transport selection; caller/source options cannot inject an adapter."""
    if API_KEY in options:raise ValueError('Transport selection is server-owned')
    if not enabled(record,node):return {**options,'response_format':{'type':'json_object'}}
    allowed={'response_format','thinking','reasoning_effort','max_tokens','temperature','timeout_seconds'}
    if set(options)-allowed:raise ValueError('Unsupported private planning options')
    return {**options,API_KEY:'responses','response_format':descriptor_for(record,node)}


def validate_options(record,node,options):
    expected=options_for_record(record,node,{k:v for k,v in options.items() if k!=API_KEY})
    return options==expected


def dispatch_options(record,node,options):
    # The frozen request includes provider identity. The tracked invoker owns
    # rebuilding that identity from the run, never a caller/source marker.
    if enabled(record,node):return {k:v for k,v in options.items() if k!=API_KEY}
    return options


def overhead_bytes(record,node):
    if not enabled(record,node):return 0
    return len(json.dumps({API_KEY:'responses','response_format':descriptor_for(record,node)},
        ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8'))
