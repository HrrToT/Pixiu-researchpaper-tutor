"""Explicit selected axes and methods survive decoding, checks and presentation."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from services.deep_research.workflow_initialization_structured import (
    MARKER, POLICY, enabled, descriptor, decode, parse, selection, method, issues,
    selector_text, method_text)
from services.deep_research.workflow_initialization_recipe import MARKER as RECIPE
from services.deep_research.workflow_initialization_context import descriptor as previous_descriptor
from services.deep_research.workflow_units import INIT, unit_errors
from services.deep_research.operation_text import operation_text
from services.deep_research.contracts import DeepResearchError
import test_deep_research_workflow_initialization_context as previous
from test_deep_research_initialization_state_contract import record as previous_record


def record(): return {**previous_record(), RECIPE:1, MARKER:1}


def structured(wire):
    wire = deepcopy(wire); init = wire['initialization']
    if init['initializationMode'] == 'derive':
        for item in [init['input'], *init['additionalInputs']]:
            item['selector'] = {'entity':item['selector'], 'fields':['values'],
                'axes':['selected entity rows', 'value channels']}
        init['stateDefinitions'][0]['initializer'] = {'mode':'operation','inputIndices':[0],
            'rule':{'action':'copy selected values',
                'parameter':{'name':'columns','type':'choice','value':'all selected value channels'},
                'additionalParameters':[]}}
    for state in init['stateDefinitions']:
        initializer = state['initializer']
        if initializer['mode'] == 'operation':
            initializer['rule'].update(steps=['Apply the declared transformation with its parameters'],
                outputLayout='Declared output state shape and dtype')
    return wire


def setup():
    r, invoke, run = previous.setup(); r.update({RECIPE:1, MARKER:1, 'workflowInitializationContextContractVersion':2})
    calls=list(invoke.side_effect)
    for call in calls[1:]: call['content']=json.dumps(structured(json.loads(call['content'])))
    invoke.side_effect=calls
    return r,invoke,run


@pytest.mark.parametrize('value',[None,False,True,0,2,'1'])
def test_strict_version_cannot_enable_structured_recipes(value):
    r=record(); r[MARKER]=value; assert not enabled(r)


def test_structured_requires_all_parent_contracts():
    assert enabled(record())
    for key in (RECIPE,'workflowInitializationContextContractVersion','workflowInitializationRepairContractVersion'):
        r=record();r.pop(key);assert not enabled(r)


def fixture():
    _,_,inits=previous.fixtures()
    from test_deep_research_workflow_initialization_wire import to_wire
    wire=structured(to_wire(inits[-1]));assert wire['initialization']['initializationMode']=='derive'
    return wire


def test_native_schema_requires_explicit_selection_and_method_steps():
    wire=fixture();schema=descriptor('component')['schema'];Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    bad=deepcopy(wire);bad['initialization']['input']['selector']='training_data'
    with pytest.raises(ValidationError): Draft202012Validator(schema).validate(bad)
    for state in wire['initialization']['stateDefinitions']:
        if state['initializer']['mode']=='operation':
            state['initializer']['rule']['steps']=[]
            with pytest.raises(ValidationError):Draft202012Validator(schema).validate(wire)
            break


def test_lossless_interface_and_method_definitions_are_retained():
    wire=fixture();before=deepcopy(wire);value=decode(wire);init=value['initialization']
    assert wire==before and parse(json.dumps(wire))==value
    assert selection(init['inputs'][0]['selector'])==wire['initialization']['input']['selector']
    for original, state in zip(wire['initialization']['stateDefinitions'],init['stateDefinitions']):
        assert state['shape']==original['shape'] and state['dtype']==original['dtype']
        if state['initializer']['mode']=='operation':
            rule=original['initializer']['rule'];canonical=state['initializer']['rule']
            assert method(canonical['action'])=={'name':rule['action'],'steps':rule['steps'],'outputLayout':rule['outputLayout']}
            assert canonical['parameters']==[rule['parameter'],*rule['additionalParameters']]
            assert '输出布局' in operation_text(canonical) and '@initializer-method' not in operation_text(canonical)
    assert issues(init)==[]


@pytest.mark.parametrize('axis',[2,17])
def test_axis_must_exist_in_the_selected_entity_not_just_be_nonnegative(axis):
    value=decode(fixture());init=value['initialization']
    init['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':axis},3]
    found=issues(init);assert found[0]['code']=='unit.initialization.input_axis'
    assert found[0]['declaredAxes']==['selected entity rows','value channels']
    _,meta,_=previous.fixtures()
    aliases={ref:ref for ref in value['sourceRefs']}
    assert 'unit.initialization.input_axis' in unit_errors(value,aliases,node=INIT,version=7,
        metadata=meta,target=meta['components'][-1],earlier=meta['components'][:-1],structured_initialization=True)
    assert 'unit.initialization.input_axis' not in unit_errors(value,aliases,node=INIT,version=7,
        metadata=meta,target=meta['components'][-1],earlier=meta['components'][:-1])


@pytest.mark.parametrize('change',['entity','fields','axes','extra','steps','output'])
def test_decoder_does_not_fill_missing_definitions(change):
    wire=fixture();selector=wire['initialization']['input']['selector']
    if change in ('entity','fields','axes'):selector.pop(change)
    elif change=='extra':selector['guess']='not allowed'
    else:
        state=next(s for s in wire['initialization']['stateDefinitions'] if s['initializer']['mode']=='operation')
        state['initializer']['rule'].pop('steps' if change=='steps' else 'outputLayout')
    with pytest.raises(ValueError):decode(wire)


def test_legacy_schema_and_text_are_unchanged():
    old=previous_descriptor('component');before=deepcopy(old);descriptor('component')
    assert previous_descriptor('component')==before
    for text in ('all rows','{"entity":"not a complete recipe"}','@initializer-input/v1:bad'):
        assert selector_text(text)==text
    assert method_text('copy values')=='copy values'


def test_complete_workflow_reopens_without_new_calls_and_displays_interfaces():
    r,invoke,run=setup();saved=run();assert saved['status']=='ready'
    assert saved['request']['initializationStructuredRecipeContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT: assert POLICY in call.args[1]
    count=invoke.call_count;assert run()==saved and invoke.call_count==count
    from services.deep_research.workflow_lifecycle_text import lifecycle_text
    text=lifecycle_text(saved['value']['workflow'])
    assert '字段：' in text and '轴0：' in text and '@initializer-input' not in text
    assert '输出布局' in text and '@initializer-method' not in text


def test_saved_unstructured_units_cannot_be_upgraded():
    r,invoke,run=previous.setup();run();count=invoke.call_count
    r.update({RECIPE:1,MARKER:1,'workflowInitializationContextContractVersion':2})
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_axis_failure_uses_the_single_durable_repair_with_actual_definitions():
    r,invoke,run=setup();calls=list(invoke.side_effect);bad=deepcopy(calls[-1])
    wire=json.loads(bad['content']);wire['initialization']['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':9}]
    bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    saved=r['state']['executionWorkflowBlueprint'];repair=saved['initializationRepair']
    assert repair['status']=='invalid_response' and POLICY in repair['request']['prompt']
    assert 'declaredAxes' in repair['request']['prompt']
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_http_schema_size_budget_and_unknown_request_are_bound(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(previous,'record',record)
    previous.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_server_owns_structured_contract_and_prevents_migration(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design',
            'deferStart':True,MARKER:replacement},start_async=False)
        assert r[MARKER]==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda old:{**old,MARKER:replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(MARKER);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda item:{**item,MARKER:1})
    finally:facade.shutdown()


def test_unicode_newlines_and_separators_do_not_drop_or_reinterpret_values():
    wire=fixture();raw_selector=wire['initialization']['input']['selector']
    raw_selector.update(entity='点表；<script>\n"quoted"',fields=['x,y','颜色\\通道'])
    value=decode(wire)
    encoded=value['initialization']['inputs'][0]['selector']
    assert selection(encoded)==raw_selector and selector_text(encoded).startswith(raw_selector['entity'])
    from services.deep_research.workflow_lifecycle_text import _input
    displayed=_input(value['initialization']['inputs'][0])
    assert '<script>' not in displayed and '&lt;script&gt;' in displayed
