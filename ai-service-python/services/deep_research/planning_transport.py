"""Frozen schema transport for new private plans, independent of source support."""
import json
from llm.responses_transport import API_KEY


def enabled(record,node):
    from services.deep_research.scientific_outline import enabled as outline_enabled,NODE
    if node==NODE and outline_enabled(record):return True
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


def descriptor_for(record, node, initialization_target='component', *, metadata_edits=False, revision_source_refs=None, fit_edits=False):
    from services.deep_research import workflow_fit_edits as fits
    if type(fit_edits) is not bool: raise ValueError('Invalid fit edit mode')
    if fit_edits:
        if node!=fits.NODE or not fits.enabled(record) or metadata_edits or revision_source_refs is not None:
            raise ValueError('Invalid fit edit mode')
        return fits.descriptor(record['workflowFitEditsContractVersion'])
    if revision_source_refs is not None:
        from services.deep_research import workflow_revision_sources as sources
        if node!='repair_workflow_meta' or metadata_edits or not sources.enabled(record):
            raise ValueError('Invalid metadata source binding mode')
        return sources.bind_descriptor(descriptor_for(record,node,initialization_target),revision_source_refs)
    from services.deep_research.workflow_metadata_edits import enabled as edits_enabled, NODE as EDIT_NODE, descriptor as edits_descriptor
    if type(metadata_edits) is not bool: raise ValueError('Invalid metadata edit mode')
    if metadata_edits:
        if node != EDIT_NODE or not edits_enabled(record): raise ValueError('Metadata edit mode is not enabled')
        return edits_descriptor()
    from services.deep_research.workflow_metadata_repair import enabled as repair_enabled, NODE as REPAIR_META
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 34):
        from services.deep_research.workflow_metadata_symbols import descriptor as symbolic_descriptor
        return symbolic_descriptor()
    from services.deep_research.workflow_initialization_wire import enabled as init_enabled, descriptor as init_descriptor
    if node == 'plan_workflow_init' and init_enabled(record):
        from services.deep_research.workflow_initialization_readable import enabled as readable, descriptor as readable_descriptor
        if readable(record):return readable_descriptor(initialization_target)
        from services.deep_research.workflow_initialization_semantics import enabled as semantics, descriptor as semantics_descriptor
        if semantics(record):return semantics_descriptor(initialization_target)
        from services.deep_research.workflow_initialization_structured import enabled as structured, descriptor as structured_descriptor
        if structured(record): return structured_descriptor(initialization_target)
        from services.deep_research.workflow_initialization_context import enabled as init_context,descriptor as state_descriptor
        if init_context(record) and record['workflowInitializationContextContractVersion']==2:
            return state_descriptor(initialization_target)
        return init_descriptor(initialization_target)
    from services.deep_research.workflow_metadata_repair import enabled as repair_enabled, NODE as REPAIR_META
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (28, 29, 30, 31, 32, 33)):
        from services.deep_research.workflow_metadata_observation_boundary import descriptor as observation_descriptor
        return observation_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 27):
        from services.deep_research.workflow_metadata_result_refs import descriptor as result_descriptor
        return result_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (25, 26, 27, 28, 29, 30, 31, 32, 33)):
        from services.deep_research.workflow_metadata_first_use import descriptor as first_use_descriptor
        return first_use_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 24):
        from services.deep_research.workflow_metadata_bounded_schema import descriptor as bounded_descriptor
        return bounded_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33)):
        from services.deep_research.workflow_metadata_compact_transport import descriptor as compact_descriptor
        return compact_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 21):
        from services.deep_research.workflow_metadata_evaluation_groups import descriptor as grouped_descriptor
        return grouped_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 20):
        from services.deep_research.workflow_metadata_fit_budget import descriptor as budget_descriptor
        return budget_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 19):
        from services.deep_research.workflow_metadata_scope_position import descriptor as scoped_descriptor
        return scoped_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 18):
        from services.deep_research.workflow_metadata_scope_start import descriptor as entrance_descriptor
        return entrance_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 17):
        from services.deep_research.workflow_metadata_scope_end import descriptor as scope_descriptor
        return scope_descriptor(frame_count_rules=True, compact_rules=True)
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 16):
        from services.deep_research.workflow_metadata_scope_end import descriptor as scope_descriptor
        return scope_descriptor(frame_count_rules=True)
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 15):
        from services.deep_research.workflow_metadata_scope_end import descriptor as scope_descriptor
        return scope_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 14):
        from services.deep_research.workflow_metadata_single_group import descriptor as scalar_descriptor
        return scalar_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] == 13):
        from services.deep_research.workflow_metadata_steps import descriptor as step_descriptor
        return step_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (11, 12)):
        from services.deep_research.workflow_metadata_ordered import descriptor as ordered_descriptor
        return ordered_descriptor(version=2 if record['workflowMetadataRepairContractVersion'] == 12 else 1)
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (8, 9, 10)):
        from services.deep_research.workflow_metadata_objects import descriptor as object_descriptor
        return object_descriptor()
    if (node in ('plan_workflow_meta', REPAIR_META) and repair_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (6, 7)):
        from services.deep_research.workflow_metadata_actions import descriptor as action_descriptor
        return action_descriptor()
    if node == REPAIR_META and repair_enabled(record):
        from services.deep_research.workflow_metadata_rows import descriptor as rows_descriptor
        return rows_descriptor()
    from services.deep_research.scientific_outline import enabled as outline_enabled,NODE,descriptor as outline_descriptor
    if node==NODE and outline_enabled(record):return outline_descriptor()
    from services.deep_research.workflow_transport import enabled as workflow_enabled, descriptor as workflow_descriptor
    if workflow_enabled(record, node) and record['executionWorkflowContractVersion'] in (6,7):
        from services.deep_research.workflow_metadata_rows import enabled as rows_enabled, descriptor as rows_descriptor
        if node == 'plan_workflow_meta' and rows_enabled(record):return rows_descriptor()
        from services.deep_research.workflow_units import descriptor as unit_descriptor
        return unit_descriptor(node,version=record['executionWorkflowContractVersion'])
    return workflow_descriptor(record['executionWorkflowContractVersion']) if workflow_enabled(record, node) else descriptor()


def options_for_record(record,node,options):
    """Own transport selection; caller/source options cannot inject an adapter."""
    if API_KEY in options:raise ValueError('Transport selection is server-owned')
    from services.deep_research.workflow_initialization_observation import enabled as observation_enabled
    from llm.response_observation import OPTION as OBSERVATION_OPTION
    observe_headers=node=='plan_workflow_init' and observation_enabled(record)
    if OBSERVATION_OPTION in options and (not observe_headers or options[OBSERVATION_OPTION] is not True):
        raise ValueError('HTTP observation is server-owned and initialization-only')
    if not enabled(record,node):return {**options,'response_format':{'type':'json_object'}}
    allowed={'response_format','thinking','reasoning_effort','max_tokens','temperature','timeout_seconds'}
    if observe_headers:allowed.add(OBSERVATION_OPTION)
    from services.deep_research import workflow_fit_edits as fits
    if fits.OPTION in options:
        if node!=fits.NODE or not fits.enabled(record) or options[fits.OPTION] is not True:
            raise ValueError('Invalid fit edit mode')
        allowed.add(fits.OPTION)
    from services.deep_research import workflow_revision_sources as sources
    if sources.OPTION in options:
        if node!='repair_workflow_meta' or not sources.enabled(record) or not sources.valid(options[sources.OPTION]):
            raise ValueError('Invalid metadata source binding mode')
        allowed.add(sources.OPTION)
    from services.deep_research.workflow_metadata_edits import OPTION as EDIT_OPTION, enabled as edits_enabled, NODE as EDIT_NODE
    if EDIT_OPTION in options:
        if node != EDIT_NODE or not edits_enabled(record) or options[EDIT_OPTION] is not True:
            raise ValueError('Invalid metadata edit mode')
        allowed.add(EDIT_OPTION)
    from services.deep_research.workflow_initialization_wire import enabled as init_enabled, TARGET_OPTION
    if node == 'plan_workflow_init' and init_enabled(record):
        allowed.add(TARGET_OPTION)
        if options.get(TARGET_OPTION) not in ('baseline', 'component'):
            raise ValueError('Initialization target must be bound before fingerprinting')
    if set(options)-allowed:raise ValueError('Unsupported private planning options')
    from services.deep_research.workflow_transport import reasoning_options
    options=reasoning_options(record,node,options)
    from services.deep_research.workflow_metadata_repair import enabled as metadata_revision_enabled
    if (node in ('plan_workflow_meta', 'repair_workflow_meta') and metadata_revision_enabled(record)
            and record['workflowMetadataRepairContractVersion'] in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33)):
        # Fixed before request fingerprinting and atomic input/output reservation.
        # Raw/canonical output and whole-run limits remain independent checks.
        # Version33 repair already has its server-owned reasoning+output cap.
        if not (node == 'repair_workflow_meta' and record['workflowMetadataRepairContractVersion'] == 33):
            options={**options,'max_tokens':6144 if record['workflowMetadataRepairContractVersion'] in (10, 29, 30, 31, 32, 33) else 3072}
    if (node=='plan_experiment' and type(record.get('experimentPlanningReasoningContractVersion')) is int
            and record['experimentPlanningReasoningContractVersion']==1):
        options={**options,'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    from services.deep_research.workflow_metadata_output import options as metadata_output_options
    options=metadata_output_options(record,node,options)
    from services.deep_research.workflow_metadata_planning_output import options as planning_output_options
    options=planning_output_options(record,node,options)
    if observe_headers:options={**options,OBSERVATION_OPTION:True}
    return {**options,API_KEY:'responses','response_format':descriptor_for(
        record,node,options.get(TARGET_OPTION, 'component'),metadata_edits=options.get(EDIT_OPTION,False),
        revision_source_refs=options.get(sources.OPTION),fit_edits=options.get(fits.OPTION,False))}


def validate_options(record,node,options):
    expected=options_for_record(record,node,{k:v for k,v in options.items() if k!=API_KEY})
    return options==expected


def dispatch_options(record,node,options):
    # The frozen request includes provider identity. The tracked invoker owns
    # rebuilding that identity from the run, never a caller/source marker.
    if enabled(record,node):return {k:v for k,v in options.items() if k!=API_KEY}
    return options


def overhead_bytes(record,node,options=None):
    if not enabled(record,node):return 0
    from services.deep_research.workflow_initialization_context import enabled as scoped_init
    target=(options or {}).get('_workflow_init_target','component') if node=='plan_workflow_init' and scoped_init(record) else 'component'
    from services.deep_research.workflow_metadata_edits import OPTION
    from services.deep_research.workflow_revision_sources import OPTION as SOURCE_OPTION
    from services.deep_research.workflow_fit_edits import OPTION as FIT_OPTION
    return len(json.dumps({API_KEY:'responses','response_format':descriptor_for(
        record,node,target,metadata_edits=(options or {}).get(OPTION,False),revision_source_refs=(options or {}).get(SOURCE_OPTION),
        fit_edits=(options or {}).get(FIT_OPTION,False))},
        ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8'))
