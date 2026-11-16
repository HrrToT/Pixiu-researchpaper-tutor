"""Input-first wire remains reversible, typed, budgeted and unverified."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_representation as types
from services.deep_research import workflow_representation_input_first as wire
from services.deep_research import workflow_representation_stage as stage
from services.deep_research.workflow_representation_dependencies import expand_schema
from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.workflow_units import INIT
import test_deep_research_workflow_representation_dependencies as previous
import test_deep_research_workflow_representation_stage as stage_tests

original_setup=previous.setup


def setup():
    record,invoke,run=original_setup();record[stage.MARKER]=3
    calls=list(invoke.side_effect)
    calls[1]['content']=json.dumps(wire.encode(json.loads(calls[1]['content'])))
    invoke.side_effect=calls
    return record,invoke,run


def fixture():
    record,value,metadata,calls=previous.fixture()
    return record,wire.encode(value),value,metadata,calls


def test_native_order_names_inputs_before_variables_and_sources_after_all_declarations():
    schema=types.descriptor(3)['schema'];Draft202012Validator.check_schema(schema)
    plain=expand_schema(schema)
    assert list(plain['properties'])==['conventions','targets','sourceRefs','unresolved']
    target=plain['properties']['targets']['items']
    assert list(target['properties'])==['target','inputDependencies','variables']
    state=target['properties']['variables']['items']
    assert list(state['properties'])[:5]==['name','quantity','encoding','dtype','shape']
    _,native,_,_,_=fixture();Draft202012Validator(schema).validate(native)


def test_indices_compile_and_roundtrip_without_supplying_variable_or_source_values():
    _,native,canonical,metadata,_=fixture();before=deepcopy(native)
    assert wire.decode(native)==canonical and native==before
    assert wire.encode(canonical)==native
    aliases={'E1':'a','E2':'b'}
    assert types.issues(canonical,metadata,aliases,version=3)==[]
    frozen=types.freeze(canonical,metadata,aliases,version=3)
    assert frozen['version']==3 and frozen['scientificApproval'] is False
    assert types.verify(frozen,metadata,aliases)==canonical
    assert 'initializer' not in json.dumps(native)


@pytest.mark.parametrize('change',['input_missing','axis_missing','input_negative','axis_negative',
    'input_bool','axis_bool','input_float','unknown_key','self_named','old_states_field','missing_variables',
    'missing_dependency_source','non_object_dependency','missing_phase_id','missing_selected_fields'])
def test_invalid_wire_cannot_guess_inputs_or_silently_upgrade_named_dimensions(change):
    _,native,_,_,_=fixture();target=native['targets'][-1];dim=target['variables'][0]['shape'][0]
    assert isinstance(dim,dict)
    if change=='input_missing':dim['inputIndex']=len(target['inputDependencies'])
    elif change=='axis_missing':dim['axis']=99
    elif change=='input_negative':dim['inputIndex']=-1
    elif change=='axis_negative':dim['axis']=-1
    elif change=='input_bool':dim['inputIndex']=False
    elif change=='axis_bool':dim['axis']=True
    elif change=='input_float':dim['inputIndex']=0.0
    elif change=='unknown_key':dim['state']='target'
    elif change=='self_named':target['variables'][0]['shape'][0]={'state':target['target'],'entity':'model','fields':['parameters'],'axis':'row'}
    elif change=='old_states_field':target['states']=target.pop('variables')
    elif change=='missing_variables':target.pop('variables')
    elif change=='missing_dependency_source':target['inputDependencies'][0].pop('input')
    elif change=='missing_phase_id':target['inputDependencies'][0]['input'].pop('phaseId')
    elif change=='missing_selected_fields':target['inputDependencies'][0]['input']['selector'].pop('fields')
    else:target['inputDependencies'][0]=None
    with pytest.raises(ValueError):wire.decode(native)


@pytest.mark.parametrize('change,code',[('namespace','representation.variable_namespace'),
    ('source_union','representation.source_closure'),('missing_dtype','representation.schema'),
    ('float_dimension','representation.dimension_type'),('missing_variable','representation.schema')])
def test_compile_does_not_repair_inventories_or_paper_attributions(change,code):
    _,native,_,metadata,_=fixture();target=native['targets'][0]
    if change=='namespace':target['variables'][0]['name']=target['target']
    elif change=='source_union':native['sourceRefs']=[]
    elif change=='missing_dtype':target['variables'][0].pop('dtype')
    elif change=='float_dimension':target['variables'][0]['shape']=[3.0]
    else:target['variables']=[]
    canonical=wire.decode(native)
    assert code in {e['code'] for e in types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=3)}
    with pytest.raises(ValueError):types.freeze(canonical,metadata,{'E1':'a','E2':'b'},version=3)


def test_input_axis_reordering_is_exactly_retained_in_native_and_canonical_views():
    _,native,_,metadata,_=fixture();target=native['targets'][-1]
    target['inputDependencies'][0]['input']['selector']['axes'].reverse()
    target['variables'][0]['shape'][0]['axis']=1
    canonical=wire.decode(native)
    assert wire.encode(canonical)==native
    assert types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=3)==[]


def test_old_v2_schema_digest_and_canonical_declarations_remain_frozen():
    assert digest(types.descriptor(2))=='45a8b0bcc41428cc01921b7025ce1d2f471da0823d9c691e7a9769f74c1fc618'
    _,_,canonical,metadata,_=fixture();aliases={'E1':'a','E2':'b'}
    v2=types.freeze(canonical,metadata,aliases,version=2)
    assert types.verify(v2,metadata,aliases)==canonical
    assert v2['version']==2


def test_complete_v3_workflow_preserves_raw_wire_compiles_values_and_reopens():
    record,invoke,run=setup();saved=run()
    assert saved['status']=='ready' and saved['representation']['version']==3
    shared=saved['representation'];raw=json.loads(shared['response']['content'])
    assert 'variables' in raw['targets'][0] and 'states' not in raw['targets'][0]
    assert wire.decode(raw)==shared['value'] and shared['frozen']['version']==3
    assert invoke.call_count==5
    for key,unit in saved['units'].items():
        if key=='metadata':continue
        assert unit['premiseAllocation']['version']==2
        assert unit['premiseAllocation']['requiredAliases']==['E1']
        assert unit['request']['extra']['response_format']['name'].startswith('workflow_init_representation_v3_')
    assert run()==saved and invoke.call_count==5


def test_cached_v2_cannot_be_upgraded_to_v3_and_regenerate_any_unit():
    record,invoke,run=original_setup();run();count=invoke.call_count;record[stage.MARKER]=3
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('change',['self_named','missing_variable','namespace'])
def test_bad_v3_declaration_stops_before_initialization_and_does_not_retry(change):
    record,invoke,run=setup();calls=list(invoke.side_effect);value=json.loads(calls[1]['content'])
    target=value['targets'][0]
    if change=='self_named':target['variables'][0]['shape']=[{'state':'baseline','entity':'model','fields':['all'],'axis':'row'}]
    elif change=='namespace':target['variables'][0]['name']=target['target']
    else:target['variables']=[]
    calls[1]['content']=json.dumps(value);invoke.side_effect=calls
    with pytest.raises(DeepResearchError):run()
    shared=record['state']['executionWorkflowBlueprint']['representation']
    assert shared['status']=='invalid_response' and shared['frozen'] is None and invoke.call_count==2
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2


def test_sole_initializer_correction_keeps_v3_types_and_source_scope():
    record,invoke,run=setup();calls=list(invoke.side_effect);good=deepcopy(calls[-1]);bad=deepcopy(good)
    value=json.loads(bad['content']);value['initialization']['stateDefinitions'][0]['dtype']='other'
    bad['content']=json.dumps(value);invoke.side_effect=[*calls[:-1],bad,good]
    saved=run();repair=saved['initializationRepair']
    assert saved['status']=='ready' and repair['status']=='ready' and invoke.call_count==6
    assert repair['request']['extra']['response_format']['name'].startswith('workflow_init_representation_v3_')
    assert 'representation.dtype_changed' in repair['parent']['errors']
    assert run()==saved and invoke.call_count==6


@pytest.mark.parametrize('node',[stage.NODE,INIT])
@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_v3_http_ledger_budget_and_unknown_no_resend(tmp_path,monkeypatch,node,scenario):
    monkeypatch.setattr(stage_tests,'setup',setup)
    stage_tests.test_actual_provider_payload_ledger_identity_capacity_and_unknown_no_resend(tmp_path,monkeypatch,node,scenario)
