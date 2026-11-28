"""Readable inputs and schema sharing preserve all source values and constraints."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research.workflow_initialization_readable import (
    MARKER, TEXT, enabled, input_text, descriptor, expand_schema)
from services.deep_research.workflow_initialization_semantics import descriptor as previous_descriptor
from services.deep_research.workflow_units import INIT
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_reasoning as reasoning_tests
import test_deep_research_initialization_semantics as semantics_tests
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


def record():return {**reasoning_tests.record(),MARKER:1}


@pytest.mark.parametrize('marker',[None,False,True,0,2,'1'])
def test_readability_is_a_strict_frozen_profile(marker):
    r=record();r[MARKER]=marker;assert not enabled(r)


def test_profile_requires_initialization_reasoning_parent():
    r=record();assert enabled(r);r.pop(reasoning_tests.MARKER);assert not enabled(r)


def test_all_reserved_literals_quotes_unicode_and_scalar_types_round_trip():
    from services.deep_research import shared_strings,nested_tables
    source={'authoritativeInput':{'question':'中文 "quoted"\n question',
        'unverifiedScientificPlan':{'protocol':{'state':'full original state'}},
        'evidence':[{'evidenceId':str(i),'quote':'long exact source '*70,
            'sourceContext':{'$':i,'~':{'@':['literal']},'!':False}}
            for i in range(12)]},'unitContext':{'allTypes':[None,True,1,1.0,False,0]}}
    before=deepcopy(source);body=input_text(source);wire=json.loads(body.splitlines()[0])
    assert set(wire)=={'strings','value'}
    restored=nested_tables.unpack(shared_strings.unpack(wire))
    assert json.dumps(restored,ensure_ascii=False)==json.dumps(source,ensure_ascii=False)
    assert source==before and '"authoritativeInput"' in body
    assert not set(wire)&{'keys','boundInput','stateDecision'}


def test_small_input_stays_literal_named_json():
    source={'authoritativeInput':{'question':'q'},'unitContext':{'target':'baseline'}}
    assert input_text(source)==json.dumps(source,ensure_ascii=False,separators=(',',':'))


@pytest.mark.parametrize('target',['baseline','component'])
def test_shared_schema_expands_to_every_original_constraint(target):
    old=previous_descriptor(target);new=descriptor(target)
    assert new['name']==old['name'] and new['schema']['$defs']['t']==TEXT
    assert expand_schema(new['schema'])==old['schema']
    assert len(json.dumps(new))<len(json.dumps(old))
    Draft202012Validator.check_schema(new['schema'])


@pytest.mark.parametrize('change',['valid','empty_name','empty_meaning','extra_key','wrong_shape_type'])
def test_native_validation_result_matches_original_schema(change):
    wire=semantics_tests.with_semantics(semantics_tests.structured_tests.fixture())
    if change=='empty_name':wire['initialization']['stateDefinitions'][0]['name']=''
    elif change=='empty_meaning':wire['stateSemantics'][0][1]=''
    elif change=='extra_key':wire['foreign']='value'
    elif change=='wrong_shape_type':wire['initialization']['stateDefinitions'][0]['shape']=['N']
    before=Draft202012Validator(previous_descriptor('component')['schema']).is_valid(wire)
    after=Draft202012Validator(descriptor('component')['schema']).is_valid(wire)
    assert before==after==(change=='valid')


def test_unowned_schema_alias_collision_is_rejected(monkeypatch):
    old=previous_descriptor('baseline');old['schema']['$defs']['t']={'type':'number'}
    monkeypatch.setattr('services.deep_research.workflow_initialization_semantics.descriptor',lambda *_:deepcopy(old))
    with pytest.raises(ValueError,match='already owned'):descriptor('baseline')


def test_complete_workflow_and_resume_preserve_semantics_and_source_values():
    r,invoke,run=semantics_tests.setup();r.update({reasoning_tests.MARKER:1,MARKER:1})
    saved=run();assert saved['status']=='ready' and saved['request']['initializationReadableInputContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT:
            restored=input_value(call.args[1])
            assert restored['authoritativeInput']['question']=='Full 2x2 request, not shortened'
            assert restored['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']=='unchanged proposal'
            assert call.args[2]['response_format']['schema']['$defs']['t']==TEXT
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_existing_reasoning_workflow_cannot_switch_representation():
    r,invoke,run=semantics_tests.setup();r[reasoning_tests.MARKER]=1;run();count=invoke.call_count
    r[MARKER]=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_unique_repair_retains_original_invalid_semantics_and_plain_named_keys():
    r,invoke,run=semantics_tests.setup();r.update({reasoning_tests.MARKER:1,MARKER:1})
    calls=list(invoke.side_effect);bad=deepcopy(calls[-1]);wire=json.loads(bad['content'])
    wire['stateSemantics'][0][0]='unknown_state';bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    fix=r['state']['executionWorkflowBlueprint']['initializationRepair']
    assert input_value(fix['request']['prompt'])['invalidInitialization']==wire
    assert fix['request']['extra']['response_format']['schema']['$defs']['t']==TEXT
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_server_owns_marker_and_forbids_mutation_or_legacy_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,MARKER:replacement},start_async=False)
        assert r[MARKER]==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda old:{**old,MARKER:replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(MARKER);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda item:{**item,MARKER:1})
    finally:facade.shutdown()


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_http_shared_schema_capacity_budget_and_no_unknown_resend(tmp_path,monkeypatch,scenario):
    from llm import responses_transport
    sent=[];original=responses_transport.payload
    def capture(*args,**kwargs):
        value=original(*args,**kwargs);sent.append(deepcopy(value));return value
    monkeypatch.setattr(responses_transport,'payload',capture);monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
    if scenario=='budget':assert not sent
    else:
        assert len(sent)==1 and sent[0]['reasoning']=={'effort':'low'}
        assert sent[0]['text']['format']['schema']['$defs']['t']==TEXT
