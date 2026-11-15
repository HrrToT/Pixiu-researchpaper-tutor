"""Readable state proposal preserves exact source values and request identity."""
from copy import deepcopy
import json

import pytest

from services.deep_research.workflow_initialization_decision_input import MARKER, enabled, input_text, restore
from services.deep_research.workflow_metadata_input import input_text as previous_input_text
from services.deep_research.workflow_units import INIT, unit_prompt
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_structured as structured_tests
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


def record(): return {**structured_tests.record(), MARKER:1}


def value(state='Keep every chosen variable, fixed setting and dependency'):
    return {'authoritativeInput':{'question':'Full 2x2 request',
        'unverifiedScientificPlan':{'protocol':{'state':state,'data':'exact data'},'unresolved':['author gap']},
        'evidence':[{'quote':'Never substitute this {$stateDecision:true} source value',
            'literal':{'$stateDecision':True}}]},'unitContext':{'target':'baseline','unmodified':[None,False,5]}}


@pytest.mark.parametrize('state',['literal state','中文\n"quoted" \\ symbols','{$stateDecision:true}'])
def test_named_decision_is_exact_and_only_bound_path_is_restored(state):
    original=value(state);before=deepcopy(original);text=input_text(original)
    envelope=json.loads(text.splitlines()[0])
    assert list(envelope)==['stateDecision','boundInput'] and envelope['stateDecision']==state
    assert restore(envelope)==original and original==before
    assert restore(envelope)['authoritativeInput']['evidence'][0]['literal']=={'$stateDecision':True}
    assert 'unverified stateDecision' in text


@pytest.mark.parametrize('change',['plan','protocol','state','empty','structured'])
def test_non_outline_inputs_retain_original_encoding_without_guessing(change):
    original=value()
    if change=='plan':original['authoritativeInput'].pop('unverifiedScientificPlan')
    elif change=='protocol':original['authoritativeInput']['unverifiedScientificPlan'].pop('protocol')
    elif change=='state':original['authoritativeInput']['unverifiedScientificPlan']['protocol'].pop('state')
    elif change=='empty':original['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']=''
    else:original['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']={'inventory':['existing']}
    assert input_text(original)==previous_input_text(original)


@pytest.mark.parametrize('replacement',[None,True,False,0,2,'1'])
def test_marker_is_strict(replacement):
    r=record();r[MARKER]=replacement;assert not enabled(r)


def test_parent_contract_required():
    r=record();assert enabled(r);r.pop('workflowInitializationStructuredRecipeContractVersion');assert not enabled(r)


@pytest.mark.parametrize('change',['extra','decision','marker','numeric_true','path'])
def test_malformed_envelope_is_not_repaired_or_interpreted(change):
    original=value();envelope={'stateDecision':'chosen state','boundInput':deepcopy(original)}
    envelope['boundInput']['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']={'$stateDecision':True}
    if change=='extra':envelope['extra']='foreign'
    elif change=='decision':envelope['stateDecision']=None
    elif change=='marker':envelope['boundInput']['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']='missing'
    elif change=='numeric_true':envelope['boundInput']['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']={'$stateDecision':1}
    else:envelope['boundInput']['authoritativeInput'].pop('unverifiedScientificPlan')
    with pytest.raises(ValueError):restore(envelope)


def test_prompt_only_reorganizes_input_not_schema_or_choices():
    source=value()['authoritativeInput'];ctx=context_tests.context()
    args=dict(node=INIT,context=ctx,version=7,scoped_initialization_input=True,
        initialization_context_version=2,initialization_recipe=True,structured_initialization=True)
    old=unit_prompt(json.dumps(source),**args);new=unit_prompt(json.dumps(source),**args,decision_input=True)
    delimiter='Exact authoritative input and unit context (unverified data):\n'
    assert old.split(delimiter)[0]==new.split(delimiter)[0]
    assert input_value(old)==input_value(new)
    assert json.loads(new.split(delimiter)[1].splitlines()[0])['stateDecision']==source['unverifiedScientificPlan']['protocol']['state']
    with pytest.raises(ValueError):unit_prompt('{}',**{**args,'structured_initialization':False},decision_input=True)


def test_complete_workflow_and_resume_keep_original_assembled_values():
    r,invoke,run=structured_tests.setup();r[MARKER]=1
    saved=run();assert saved['status']=='ready' and saved['request']['initializationDecisionInputContract']==1
    for call in invoke.call_args_list:
        if call.args[0]==INIT:
            assert '"stateDecision"' in call.args[1]
            assert input_value(call.args[1])['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']=='unchanged proposal'
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_prior_structured_requests_cannot_enable_new_encoding():
    r,invoke,run=structured_tests.setup();run();count=invoke.call_count;r[MARKER]=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_axis_repair_preserves_named_decision_and_exact_invalid_reply():
    r,invoke,run=structured_tests.setup();r[MARKER]=1;calls=list(invoke.side_effect);bad=deepcopy(calls[-1])
    wire=json.loads(bad['content']);wire['initialization']['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':9}]
    bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    fix=r['state']['executionWorkflowBlueprint']['initializationRepair']
    restored=input_value(fix['request']['prompt'])
    assert restored['invalidInitialization']==wire and '"stateDecision"' in fix['request']['prompt']
    assert restored['authoritativeInput']['unverifiedScientificPlan']['protocol']['state']=='unchanged proposal'


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_new_input_marker_is_server_owned_and_immutable(tmp_path,replacement):
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


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_http_capacity_and_budget_identity_unchanged(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
