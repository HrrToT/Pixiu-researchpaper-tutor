"""Explicit meaning/encoding coverage is distinct from scientific acceptance."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from services.deep_research.workflow_initialization_semantics import (
    POLICY, descriptor, decode, parse, rows, issues, layout_text)
from services.deep_research.workflow_initialization_numeric import MARKER
from services.deep_research.workflow_units import INIT, unit_errors
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_selection as selection_tests
import test_deep_research_initialization_numeric as numeric_tests
import test_deep_research_initialization_structured as structured_tests
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


def record():return {**numeric_tests.record(),MARKER:3}


def with_semantics(wire):
    wire=deepcopy(wire)
    wire['stateSemantics']=[[s['name'],'Explicit proposed quantity '+s['name'],'identity mapping, fixture units']
        for s in wire['initialization']['stateDefinitions']]
    return wire


def setup():
    r,invoke,run=structured_tests.setup();r.update({numeric_tests.decision_tests.MARKER:1,MARKER:3})
    calls=list(invoke.side_effect)
    for call in calls[1:]:call['content']=json.dumps(with_semantics(json.loads(call['content'])))
    invoke.side_effect=calls
    return r,invoke,run


def test_native_rows_are_required_and_exactly_three_nonempty_strings():
    wire=with_semantics(structured_tests.fixture());schema=descriptor('component')['schema']
    Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(wire)
    for value in ([],[['name','quantity']], [['name','quantity',5]], [['name','quantity','']]):
        bad=deepcopy(wire);bad['stateSemantics']=value
        with pytest.raises(ValidationError):Draft202012Validator(schema).validate(bad)
    wire.pop('stateSemantics')
    with pytest.raises((ValueError,ValidationError)):decode(wire)


def test_every_authored_row_and_existing_value_is_preserved_without_mutation():
    wire=with_semantics(structured_tests.fixture());before=deepcopy(wire);canonical=decode(wire)
    original=structured_tests.decode({k:v for k,v in wire.items() if k!='stateSemantics'})
    assert wire==before and parse(json.dumps(wire))==canonical
    assert rows(canonical['initialization'])==wire['stateSemantics']
    stripped=deepcopy(canonical);stripped['initialization']['creation']['parameters'].pop()
    assert stripped==original and issues(canonical['initialization'])==[]


@pytest.mark.parametrize('change',['missing','duplicate','unknown','blank','wrong_width','not_list'])
def test_incomplete_or_foreign_state_meanings_are_preserved_but_rejected(change):
    wire=with_semantics(structured_tests.fixture())
    if change=='missing':wire['stateSemantics'].pop()
    elif change=='duplicate':wire['stateSemantics'].append(deepcopy(wire['stateSemantics'][0]))
    elif change=='unknown':wire['stateSemantics'][0][0]='not_a_declared_state'
    elif change=='blank':wire['stateSemantics'][0][1]=' '
    elif change=='wrong_width':wire['stateSemantics'][0].append('foreign')
    else:wire['stateSemantics']=None
    value=decode(wire);found=issues(value['initialization'])
    assert found and rows(value['initialization'])==wire['stateSemantics']
    assert all(item['path'].startswith('/stateSemantics') for item in found)
    _,meta,_=context_tests.fixtures()
    errors=unit_errors(value,{ref:ref for ref in value['sourceRefs']},node=INIT,version=7,
        metadata=meta,target=meta['components'][-1],earlier=meta['components'][:-1],
        structured_initialization=True,semantic_initialization=True)
    assert any(code.startswith('unit.initialization.state_semantics') for code in errors)


def test_manual_state_layout_is_not_overwritten_or_silently_selected():
    wire=with_semantics(structured_tests.fixture());manual={'name':'state_layout','type':'choice','value':'manual layout'}
    wire['initialization']['creation']['parameters'].append(manual)
    value=decode(wire);assert value['initialization']['creation']['parameters'][-2]==manual
    assert issues(value['initialization']) and rows(value['initialization']) is None


def test_escaped_layout_still_obeys_existing_canonical_output_cap():
    wire=with_semantics(structured_tests.fixture());wire['stateSemantics'][0][2]='"'*2000
    value=decode(wire)
    packed=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()
    assert len(packed(wire))<=8192<len(packed(value))
    _,meta,_=context_tests.fixtures()
    errors=unit_errors(value,{ref:ref for ref in value['sourceRefs']},node=INIT,version=7,
        metadata=meta,target=meta['components'][-1],earlier=meta['components'][:-1],
        structured_initialization=True,semantic_initialization=True)
    assert 'unit.output_capacity' in errors


def test_readable_layout_escapes_at_existing_report_boundary_and_keeps_original():
    wire=with_semantics(structured_tests.fixture());wire['stateSemantics'][0][1]='量；<script>\n"原值"'
    value=decode(wire);layout=value['initialization']['creation']['parameters'][-1]['value']
    assert '物理量' in layout_text(layout) and '@initializer-state-semantics' not in layout_text(layout)
    assert rows(value['initialization'])==wire['stateSemantics']
    from services.deep_research.workflow_lifecycle_text import _initialization
    text='\n'.join(_initialization(value['initialization'],'title'))
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert layout_text('legacy state description')=='legacy state description'


def test_complete_workflow_keeps_semantics_for_every_initializer_and_reopens():
    r,invoke,run=setup();saved=run();assert saved['status']=='ready'
    wf=saved['value']['workflow']
    for init in [wf['baselineInitialization'],*wf['componentInitializations']]:
        assert issues(init)==[] and len(rows(init))==len(init['stateDefinitions'])
    for call in invoke.call_args_list:
        if call.args[0]==INIT:assert POLICY in call.args[1]
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_v2_cached_workflow_cannot_enable_semantics_and_resend():
    r,invoke,run=structured_tests.setup();r.update({numeric_tests.decision_tests.MARKER:1,MARKER:2})
    run();count=invoke.call_count;r[MARKER]=3
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_bad_coverage_has_one_durable_repair_with_exact_invalid_semantics():
    r,invoke,run=setup();calls=list(invoke.side_effect);bad=deepcopy(calls[-1]);wire=json.loads(bad['content'])
    wire['stateSemantics'][0][0]='unknown_state';bad['content']=json.dumps(wire);calls[-1]=bad
    invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    repair=r['state']['executionWorkflowBlueprint']['initializationRepair']
    restored=input_value(repair['request']['prompt'])
    assert repair['status']=='invalid_response' and restored['invalidInitialization']==wire
    assert 'unit.initialization.state_semantics_coverage' in repair['errors']
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_v4_real_http_capacity_budget_and_unknown_no_resend(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
