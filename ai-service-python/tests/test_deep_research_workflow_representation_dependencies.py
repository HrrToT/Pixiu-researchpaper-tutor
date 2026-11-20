"""V2 inputs and complete original-source closure, never ranked or truncated."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_representation as types
from services.deep_research import workflow_representation_stage as stage
from services.deep_research import workflow_representation_dependencies as deps
from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.workflow_initialization_semantics import decode
from services.deep_research.workflow_initialization_wire import TARGET_OPTION
from services.deep_research.workflow_units import INIT
from services.deep_research.planning_transport import options_for_record, overhead_bytes
from services.deep_research.workflow_premises import allocate
from test_deep_research_workflow_metadata_ordered_integration import input_value
import test_deep_research_workflow_representation_stage as previous
original_setup=previous.setup


def setup():
    record,invoke,run=original_setup();record[stage.MARKER]=2
    calls=list(invoke.side_effect);value=json.loads(calls[1]['content'])
    for target,call in zip(value['targets'],calls[2:]):
        init=json.loads(call['content'])['initialization']
        sources=[init['input'],*init['additionalInputs']] if init['initializationMode']=='derive' else []
        target['inputDependencies']=[{'input':deepcopy(s),'origin':'proposal','sourceRefs':value['sourceRefs']} for s in sources]
    calls[1]['content']=json.dumps(value);invoke.side_effect=calls
    return record,invoke,run


def fixture():
    record,invoke,run=setup();calls=list(invoke.side_effect)
    return record,json.loads(calls[1]['content']),json.loads(calls[0]['content']),calls


def test_complete_v2_workflow_binds_inputs_and_source_closure_and_reopens_without_calls():
    record,invoke,run=setup();saved=run();assert saved['status']=='ready'
    assert saved['request']['representationContract']==2 and saved['representation']['version']==2
    assert invoke.call_count==5
    meta_data=input_value(saved['units']['metadata']['request']['prompt'])['authoritativeInput']
    for key,unit in saved['units'].items():
        if key=='metadata':continue
        audit=unit['premiseAllocation'];assert audit['version']==2
        assert audit['globalPremiseAliases']==['E1']
        assert audit['requiredAliases']==audit['suppliedAliases']==['E1']
        framed=unit['request']['prompt'].split('Exact authoritative input and unit context (unverified data):\n',1)[1]
        data=input_value(framed)['authoritativeInput']
        assert data['evidence']==[r for r in meta_data['evidence'] if r['evidenceId']=='E1']
        assert data['availableOriginalEvidenceAliases']==['E1']
        assert {k:v for k,v in data.items() if k not in ('evidence','availableOriginalEvidenceAliases')}=={
            k:v for k,v in meta_data.items() if k!='evidence'}
        assert unit['request']['extra']['response_format']['name'].startswith('workflow_init_representation_v2_')
    assert run()==saved and invoke.call_count==5


def test_native_v2_schema_reuses_identical_definitions_without_changing_validation():
    record,value,metadata,calls=fixture()
    schema=types.descriptor(2)['schema'];expanded=deps.expand_schema(schema)
    Draft202012Validator.check_schema(schema);Draft202012Validator.check_schema(expanded)
    for candidate in (value,{}, {**value,'extra':1}):
        assert bool(list(Draft202012Validator(schema).iter_errors(candidate)))==bool(list(Draft202012Validator(expanded).iter_errors(candidate)))
    assert types.issues(value,metadata,{'E1':'e1','E2':'e2'},version=2)==[]
    assert types.issues(value,metadata,{'E1':'e1','E2':'e2'},version=1)
    assert 'inputDependencies' not in types.descriptor(1)['schema']['properties']['targets']['items']['properties']


@pytest.mark.parametrize('change,code', [
    ('missing','representation.schema'),('duplicate','representation.duplicate_dependency'),
    ('future_state','representation.unavailable_dependency'),('self','representation.unavailable_dependency'),
    ('future_phase','representation.unavailable_dependency'),('unknown_output','representation.unavailable_dependency'),
    ('unknown_source','representation.provenance'),('paper_without_quote','representation.provenance'),
    ('missing_dynamic_input','representation.dimension_dependency'),
    ('wrong_axis','representation.dimension_dependency'),('ambiguous_axis','representation.dimension_dependency'),
    ('duplicate_axis','representation.schema'),('foreign_field','representation.schema')])
def test_incomplete_or_unavailable_edges_cannot_be_frozen(change,code):
    record,value,metadata,calls=fixture();target=value['targets'][-1]
    edge=target['inputDependencies'][0]
    if change=='missing':target.pop('inputDependencies')
    elif change=='duplicate':target['inputDependencies'].append(deepcopy(edge))
    elif change=='future_state':
        value['targets'][0]['inputDependencies']=[{'input':{'state':target['target'],'selector':deepcopy(edge['input']['selector'])},'origin':'proposal','sourceRefs':[]}]
    elif change=='self':edge['input']={'state':target['target'],'selector':deepcopy(edge['input']['selector'])}
    elif change=='future_phase':edge['input']['phaseId']=metadata['phases'][-1]['phaseId']
    elif change=='unknown_output':edge['input']['outputId']='not_a_declared_output'
    elif change=='unknown_source':edge['sourceRefs']=['E999']
    elif change=='paper_without_quote':edge.update(origin='paper',sourceRefs=[])
    elif change=='missing_dynamic_input':target['inputDependencies']=[]
    elif change=='wrong_axis':edge['input']['selector']['axes'][0]='image frame instead of selected rows'
    elif change=='ambiguous_axis':
        other=deepcopy(edge);other['input']['selector']['axes'].reverse();target['inputDependencies'].append(other)
    elif change=='duplicate_axis':edge['input']['selector']['axes']=['same','same']
    else:edge['inferredAvailability']=True
    errors=types.issues(value,metadata,{'E1':'e1','E2':'e2'},version=2)
    assert code in {r['code'] for r in errors}
    with pytest.raises(ValueError):types.freeze(value,metadata,{'E1':'e1','E2':'e2'},version=2)


def test_compiled_initializer_requires_exact_sources_axes_and_every_actual_value():
    record,value,metadata,calls=fixture();aliases={'E1':'e1','E2':'e2'}
    frozen=types.freeze(value,metadata,aliases,version=2);target=value['targets'][-1]['target']
    schema=types.initialization_descriptor(frozen,metadata,aliases,target)['schema']
    Draft202012Validator.check_schema(schema)
    wire=json.loads(calls[-1]['content']);Draft202012Validator(schema).validate(wire)
    assert types.initialization_issues(frozen,metadata,aliases,target,decode(wire)['initialization'])==[]
    for change in ('selector','state','missing','shape'):
        bad=deepcopy(wire)
        if change=='selector':bad['initialization']['input']['selector']['entity']='different entity'
        elif change=='state':bad['initialization']['input']={'state':'training_data','selector':wire['initialization']['input']['selector']}
        elif change=='shape':bad['initialization']['stateDefinitions'][0]['shape'][0]['axis']=1
        else:bad['initialization']['stateDefinitions'][0].pop('initializer')
        assert list(Draft202012Validator(schema).iter_errors(bad))


def test_explicit_constant_inputs_are_returned_by_model_not_filled_by_decoder():
    _,value,metadata,calls=fixture();aliases={'E1':'e1','E2':'e2'}
    frozen=types.freeze(value,metadata,aliases,version=2)
    target=value['targets'][0]['target'];schema=types.initialization_descriptor(frozen,metadata,aliases,target)['schema']
    Draft202012Validator(schema).validate(json.loads(calls[2]['content']))
    branch=schema['$defs']['initialization']['anyOf'];assert len(branch)==1
    assert branch[0]['properties']['initializationMode']=={'const':'fresh'}
    bad=json.loads(calls[-1]['content']);bad['initialization'].pop('input')
    with pytest.raises(ValueError):decode(bad)


def test_one_input_correction_obeys_v2_frozen_edges_and_cannot_increase_permissions():
    record,invoke,run=setup();calls=list(invoke.side_effect);good=deepcopy(calls[-1]);bad=deepcopy(good)
    wire=json.loads(bad['content']);wire['initialization']['input']['selector']['entity']='wrong input'
    bad['content']=json.dumps(wire);invoke.side_effect=[*calls[:-1],bad,good]
    saved=run();assert saved['status']=='ready'
    repair=saved['initializationRepair'];assert repair['status']=='ready'
    assert 'representation.inputs_changed' in repair['parent']['errors']
    assert repair['request']['extra']['response_format']['name'].startswith('workflow_init_representation_v2_')
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_v1_completed_workflow_cannot_be_reinterpreted_as_v2():
    record,invoke,run=previous.setup();run();count=invoke.call_count;record[stage.MARKER]=2
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('source,valid',[('available',True),('disposed',False),('other_group',False),('future',False)])
def test_declared_edges_respect_full_lifetime_group_and_phase_boundaries(source,valid):
    from test_deep_research_workflow_initialization_context import availability_context
    from test_deep_research_workflow_representation import fixture as base_fixture
    ctx=availability_context();metadata=ctx['metadata'];value,_,aliases,_=base_fixture()
    state=deepcopy(value['targets'][0]['states'][0]);state['shape']=[8,3]
    value['targets']=[{'target':name,'states':[deepcopy(state)],'inputDependencies':[]}
        for name in ['baseline',*[c['componentId'] for c in metadata['components']]]]
    selector={'entity':'points','fields':['xyz'],'axes':['point','coordinate']}
    inp=({'phaseId':'future','outputId':'r0','selector':selector} if source=='future' else
         {'state':source,'selector':selector})
    value['targets'][-1]['inputDependencies']=[{'input':inp,'origin':'proposal','sourceRefs':[]}]
    errors=types.issues(value,metadata,aliases,version=2)
    assert ('representation.unavailable_dependency' not in {e['code'] for e in errors}) is valid


@pytest.mark.parametrize('corrected',[True,False])
def test_unsupplied_alias_cannot_expand_scope_and_gets_only_the_original_one_correction(corrected):
    record,invoke,run=setup();calls=list(invoke.side_effect);good=deepcopy(calls[-1]);bad=deepcopy(good)
    value=json.loads(bad['content']);value['sourceRefs']=['E2'];bad['content']=json.dumps(value)
    invoke.side_effect=[*calls[:-1],bad,good if corrected else bad]
    if corrected:assert run()['status']=='ready'
    else:
        with pytest.raises(DeepResearchError):run()
    repair=record['state']['executionWorkflowBlueprint']['initializationRepair']
    assert 'unit.unsupplied_source_reference' in repair['parent']['errors']
    assert repair['status']==('ready' if corrected else 'invalid_response')
    assert invoke.call_count==6
    count=invoke.call_count
    if corrected:run()
    else:
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


def allocator_fixture():
    record,invoke,run=setup();run();saved=record['state']['executionWorkflowBlueprint']
    target=saved['representation']['value']['targets'][-1]['target']
    original=input_value(saved['units']['metadata']['request']['prompt'])['authoritativeInput']
    options={TARGET_OPTION:'component',stage.OPTION:target}
    def call(data=None):
        return allocate(record,source_data=json.dumps(original if data is None else data),context={},
            aliases=saved['aliases'],prior_values=[{'sourceRefs':['E2']}],node=INIT,
            render=lambda data,ctx:data,transport_options=options)
    return record,saved,target,original,call


def test_phase_dependencies_include_prior_state_provenance_but_not_unrelated_units():
    record,saved,target,original,call=allocator_fixture()
    before=deepcopy((saved,original));body,text,ctx,aliases,audit=call()
    assert audit['requiredAliases']==audit['suppliedAliases']==['E1']
    assert audit['globalPremiseAliases']==['E1'] and 'E2' not in aliases
    assert audit['dependencyPhases'] and 'baseline' in audit['dependencyTargets']
    assert audit['priorInitializations'] and audit['scientificApproval'] is False
    assert (saved,original)==before


@pytest.mark.parametrize('failure',['missing_row','global_premise','missing_prior','unready_prior','changed_prior'])
def test_missing_required_provenance_fails_before_render_or_send(failure):
    record,saved,target,original,call=allocator_fixture()
    if failure=='missing_row':original['evidence']=[r for r in original['evidence'] if r['evidenceId']!='E1']
    elif failure=='global_premise':record['state']['synthesisPremiseAllocation']['requiredPremiseEvidenceAliases']=['E999']
    elif failure=='missing_prior':saved['units'].pop('baseline')
    elif failure=='unready_prior':saved['units']['baseline']['status']='pending'
    else:saved['units']['baseline']['valueDigest']='changed'
    with pytest.raises(DeepResearchError):call()


def test_required_long_quotes_are_kept_whole_and_overflow_remains_visible():
    record,saved,target,original,call=allocator_fixture()
    row=next(r for r in original['evidence'] if r['evidenceId']=='E1');row['quote']='原文🙂'*10000
    _,text,_,aliases,audit=call();scoped=json.loads(text)
    assert scoped['evidence'][0]==row and set(aliases)=={'E1'}
    assert audit['inputBytes']>audit['maxInputBytes']


@pytest.mark.parametrize('node',[stage.NODE,INIT])
@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_v2_actual_http_budget_unknown_identity_and_control_removal(tmp_path,monkeypatch,node,scenario):
    monkeypatch.setattr(previous,'setup',setup)
    previous.test_actual_provider_payload_ledger_identity_capacity_and_unknown_no_resend(tmp_path,monkeypatch,node,scenario)
