"""One frozen reasoning policy; exact prompts/schema and existing budget gates."""
from copy import deepcopy
import json

import pytest

from services.deep_research.workflow_initialization_reasoning import MARKER, enabled
from services.deep_research.workflow_units import INIT
from services.deep_research.planning_transport import options_for_record
from services.deep_research.experiment_planning import request_identity
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_semantics as semantics_tests
import test_deep_research_workflow_initialization_context as context_tests


def record():return {**semantics_tests.record(),MARKER:1}


@pytest.mark.parametrize('value',[None,True,False,0,2,'1'])
def test_reasoning_requires_strict_frozen_marker(value):
    r=record();r[MARKER]=value;assert not enabled(r)


def test_semantic_initializer_profile_is_required():
    r=record();assert enabled(r);r['workflowInitializationNumericStateContractVersion']=2
    assert not enabled(r)


def test_only_reasoning_controls_change_before_fingerprinting():
    r=record();old=deepcopy(r);old.pop(MARKER)
    args={'temperature':0.0,'_workflow_init_target':'baseline'}
    before=request_identity(old,INIT,'Exact source and messages',args)
    after=request_identity(r,INIT,'Exact source and messages',args)
    assert before['prompt']==after['prompt'] and before['messages']==after['messages']
    expected=deepcopy(before['extra']);expected.update(thinking={'type':'enabled'},reasoning_effort='low')
    assert after['extra']==expected
    assert after['extra']['max_tokens']==6144 and after['extra']['timeout_seconds']==90
    for node in ('plan_workflow_meta','repair_workflow_meta','plan_experiment_outline'):
        assert options_for_record(r,node,{'temperature':0.0})==options_for_record(old,node,{'temperature':0.0})


def test_complete_workflow_and_reopen_use_one_bound_policy():
    r,invoke,run=semantics_tests.setup();r[MARKER]=1
    saved=run();assert saved['status']=='ready' and saved['request']['initializationReasoningContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT:
            assert call.args[2]['thinking']=={'type':'enabled'} and call.args[2]['reasoning_effort']=='low'
            assert call.args[2]['max_tokens']==6144 and call.args[2]['timeout_seconds']==90
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_old_completed_initializers_cannot_switch_and_resend():
    r,invoke,run=semantics_tests.setup();run();count=invoke.call_count;r[MARKER]=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_unique_repair_uses_same_thinking_budget_without_another_retry():
    r,invoke,run=semantics_tests.setup();r[MARKER]=1;calls=list(invoke.side_effect);bad=deepcopy(calls[-1])
    wire=json.loads(bad['content']);wire['stateSemantics'][0][0]='unknown_state'
    bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    fix=r['state']['executionWorkflowBlueprint']['initializationRepair']
    assert fix['request']['extra']['thinking']=={'type':'enabled'}
    assert fix['request']['extra']['max_tokens']==6144 and fix['request']['extra']['timeout_seconds']==90
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_server_owns_marker_and_blocks_mutation_or_legacy_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
            MARKER:replacement},start_async=False)
        assert r[MARKER]==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda old:{**old,MARKER:replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(MARKER);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda item:{**item,MARKER:1})
    finally:facade.shutdown()


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_real_responses_payload_and_no_unknown_or_budget_resend(tmp_path,monkeypatch,scenario):
    from llm import responses_transport
    sent=[];original=responses_transport.payload
    def capture(*args,**kwargs):
        result=original(*args,**kwargs);sent.append(deepcopy(result));return result
    monkeypatch.setattr(responses_transport,'payload',capture)
    monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
    if scenario=='budget':assert sent==[]
    else:
        assert len(sent)==1 and sent[0]['reasoning']=={'effort':'low'}
        assert sent[0]['max_output_tokens']==6144
