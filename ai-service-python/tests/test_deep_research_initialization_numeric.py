"""Numeric state instructions preserve data, native format and durable boundaries."""
from copy import deepcopy
import json

import pytest

from services.deep_research.workflow_initialization_numeric import MARKER, POLICY, enabled, bind_prompt
from services.deep_research.workflow_units import INIT, unit_prompt
from services.deep_research.planning_transport import descriptor_for, overhead_bytes
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_decision_input as decision_tests
import test_deep_research_initialization_structured as structured_tests
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


def record(): return {**decision_tests.record(), MARKER:1}


@pytest.mark.parametrize('value',[None,True,False,0,2,'1'])
def test_version_is_strict_and_cannot_enable_missing_dependencies(value):
    if type(value) is int and value==2:
        assert enabled({**record(),MARKER:value})
        return
    r=record();r[MARKER]=value;assert not enabled(r)


def test_parent_contract_and_target_boundaries_are_required():
    r=record();assert enabled(r);r.pop('workflowInitializationDecisionInputContractVersion');assert not enabled(r)
    assert 'only training_data' in bind_prompt('body','baseline')
    assert 'already available states/outputs' in bind_prompt('body','component')
    with pytest.raises(ValueError):bind_prompt('body','unknown')


def test_numeric_instructions_do_not_supply_or_change_any_value():
    source=decision_tests.value()['authoritativeInput'];ctx=context_tests.context()
    args=dict(node=INIT,context=ctx,version=7,scoped_initialization_input=True,
        initialization_context_version=2,initialization_recipe=True,structured_initialization=True,decision_input=True)
    old=unit_prompt(json.dumps(source),**args);new=unit_prompt(json.dumps(source),**args,numeric_initialization=True)
    assert new.startswith(POLICY) and input_value(new)==input_value(old)
    assert 'ONE homogeneous numeric tensor per variable' in new
    assert 'do not assume an undeclared shared/pretrained model exists' in new
    assert 'do not copy unrelated global gaps' in new
    new_record=record();old_record=deepcopy(new_record);old_record.pop(MARKER)
    for target in ('baseline','component'):
        assert descriptor_for(new_record,INIT,target)==descriptor_for(old_record,INIT,target)
        options={'_workflow_init_target':target}
        assert overhead_bytes(new_record,INIT,options)==overhead_bytes(old_record,INIT,options)
    with pytest.raises(ValueError):unit_prompt('{}',**{**args,'decision_input':False},numeric_initialization=True)


def test_complete_workflow_and_cached_reopen_preserve_values():
    r,invoke,run=structured_tests.setup();r.update({decision_tests.MARKER:1,MARKER:1})
    saved=run();assert saved['status']=='ready'
    assert saved['request']['initializationNumericStateContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT:
            assert POLICY in call.args[1] and 'WIRE V2:' not in call.args[1]
            assert input_value(call.args[1])['authoritativeInput']['question']=='Full 2x2 request, not shortened'
        else:assert POLICY not in call.args[1]
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_prior_decision_units_cannot_upgrade_and_resend():
    r,invoke,run=structured_tests.setup();r[decision_tests.MARKER]=1;run();count=invoke.call_count
    r[MARKER]=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_unique_axis_repair_uses_numeric_policy_and_keeps_original_failed_values():
    r,invoke,run=structured_tests.setup();r.update({decision_tests.MARKER:1,MARKER:1})
    calls=list(invoke.side_effect);bad=deepcopy(calls[-1]);wire=json.loads(bad['content'])
    wire['initialization']['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':9}]
    bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    repair=r['state']['executionWorkflowBlueprint']['initializationRepair']
    assert POLICY in repair['request']['prompt'] and 'WIRE V2:' not in repair['request']['prompt']
    assert input_value(repair['request']['prompt'])['invalidInitialization']==wire
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_marker_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
            MARKER:replacement},start_async=False)
        assert r[MARKER]==3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda old:{**old,MARKER:0 if replacement==2 else replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(MARKER);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda item:{**item,MARKER:1})
    finally:facade.shutdown()


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_real_http_schema_budget_and_unknown_no_resend(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
