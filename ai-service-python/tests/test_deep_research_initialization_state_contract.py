"""Native fresh dimensions agree with the no-input semantic checker."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator, ValidationError

from services.deep_research.workflow_initialization_context import descriptor, project
from services.deep_research.workflow_initialization_wire import descriptor as old_descriptor
from services.deep_research.workflow_units import unit_prompt, INIT, unit_errors
from services.deep_research.planning_transport import descriptor_for
from services.deep_research.contracts import DeepResearchError
import test_deep_research_workflow_initialization_context as previous
from test_deep_research_workflow_initialization_wire import to_wire
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_ordered_integration import input_value


_old_record = previous.record
def record(): return {**_old_record(), 'workflowInitializationContextContractVersion': 2}


def test_native_fresh_shape_rejects_input_axis_while_derive_preserves_it():
    old = old_descriptor('baseline'); new = descriptor('baseline'); before = deepcopy(old)
    Draft202012Validator.check_schema(new['schema'])
    wire = to_wire(explicit_initializers()[0]); Draft202012Validator(new['schema']).validate(wire)
    wire['initialization']['stateDefinitions'][0]['shape'] = [{'inputIndex': 0, 'axis': 0}, 3]
    Draft202012Validator(old['schema']).validate(wire)
    with pytest.raises(ValidationError): Draft202012Validator(new['schema']).validate(wire)
    init = wire['initialization']; init.pop('inputs'); init.update(initializationMode='derive',
        input={'state':'training_data','selector':'point_coordinates'},additionalInputs=[])
    Draft202012Validator(new['schema']).validate(wire)
    assert old_descriptor('baseline') == before


@pytest.mark.parametrize('dimension',[0,-1,True,'N',{'inputIndex':0,'axis':0}])
def test_fresh_dimensions_cannot_guess_an_input_or_invalid_extent(dimension):
    wire = to_wire(explicit_initializers()[0]); wire['initialization']['stateDefinitions'][0]['shape']=[dimension]
    with pytest.raises(ValidationError): Draft202012Validator(descriptor('baseline')['schema']).validate(wire)


def test_target_binding_and_derive_definitions_are_not_changed():
    for target in ('baseline','component'):
        old=old_descriptor(target);new=descriptor(target)
        assert new['schema']['$defs']['initialization']['anyOf'][1]==old['schema']['$defs']['initialization']['anyOf'][1]
        assert new['schema']['$defs']['timelineInput']==old['schema']['$defs']['timelineInput']
        assert descriptor_for(record(),INIT,target)==new
        legacy=record();legacy['workflowInitializationContextContractVersion']=1
        assert descriptor_for(legacy,INIT,target)==old


def test_state_instructions_do_not_change_evidence_or_projected_values():
    source={'question':'full four-arm experiment','evidence':[{'quote':'Exact source'}],
        'unverifiedScientificPlan':{'protocol':{'state':'keep position, opacity, scale, rotation and color states'}}}
    ctx=previous.context()
    body=unit_prompt(json.dumps(source),node=INIT,context=ctx,version=7,
        scoped_initialization_input=True,initialization_context_version=2)
    assert input_value(body)=={'authoritativeInput':source,'unitContext':project(ctx)}
    assert 'Expand every numeric state block' in body and 'fresh has no inputs' in body
    assert 'missing author settings do not forbid' in body and 'minified English JSON' in body
    old=unit_prompt(json.dumps(source),node=INIT,context=ctx,version=7,scoped_initialization_input=True)
    assert 'Expand every numeric state block' not in old


@pytest.mark.parametrize('version',[None,True,0,3,'2'])
def test_unknown_context_versions_do_not_change_prompt(version):
    with pytest.raises(ValueError):unit_prompt('{}',node=INIT,context=previous.context(),version=7,
        scoped_initialization_input=True,initialization_context_version=version)


def test_current_state_contract_assembles_same_complete_workflow(monkeypatch):
    r,invoke,run=previous.setup();r['workflowInitializationContextContractVersion']=2
    saved=run();assert saved['status']=='ready'
    assert all(u['request']['extra']['response_format']['name'].startswith('workflow_init_v2_state_')
        for k,u in saved['units'].items() if k!='metadata')
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_completed_v1_context_cannot_upgrade_or_resend():
    r,invoke,run=previous.setup();run();count=invoke.call_count
    r['workflowInitializationContextContractVersion']=2
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_v2_real_http_capacity_budget_and_unknown_identity(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(previous,'record',record)
    previous.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
