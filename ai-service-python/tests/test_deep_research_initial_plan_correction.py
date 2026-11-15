from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.initial_plan_correction import enabled,KEY,AUDIT
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from services.deep_research.contracts import BudgetExhaustedError,UnknownCallError,UnresolvedUnknownError
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker
from llm.provider import LLMResult,LLMUsage
from test_deep_research_initial_plan_response import plan
from test_deep_research_initial_plan_instructions import record


def run_record():
    return {**record(),'runId':'r','taskId':'t','initialPlanResponseContractVersion':1,KEY:1}


def execute(responses,r=None):
    saved=deepcopy(r or run_record());invoke=Mock(side_effect=responses)
    def update(rid,fn,**kwargs):
        nonlocal saved
        saved=fn(deepcopy(saved));return deepcopy(saved)
    result=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    return result,saved,invoke


def response(value=None,**extra):
    return {'content':json.dumps(plan() if value is None else value),'finishReason':'stop',**extra}


@pytest.mark.parametrize('first',[
    {'content':'null','rawContent':'{"items":[','finishReason':'stop'},
    {'content':'null','rawContent':'{"items":[]}','finishReason':'length'},
    response([]),
])
def test_known_invalid_plan_gets_one_distinct_request_and_full_validation(first):
    original=deepcopy(first)
    result,saved,invoke=execute([first,response()])
    assert result['plan_ids']==['i'] and invoke.call_count==2
    before,after=invoke.call_args_list
    assert before.args[1]==after.args[1]=='plan' and before.args[3]==after.args[3]
    assert after.args[2].startswith(before.args[2]) and 'ONE PLAN FORMAT CORRECTION' in after.args[2]
    assert saved['state']['planFormatValidation']['status']=='validated'
    assert saved['state'][AUDIT]['status']=='validated' and not saved['state'][AUDIT]['scientificApproval']
    assert first==original


def test_valid_initial_plan_does_not_spend_a_correction():
    result,saved,invoke=execute([response()])
    assert result['plan_ids']==['i'] and invoke.call_count==1 and AUDIT not in saved['state']


@pytest.mark.parametrize('mutation',['cycle','unknown_dependency','invented_excerpt','extra_field','criteria_count','source_type'])
def test_corrected_output_cannot_skip_existing_plan_gates(mutation):
    value=plan();o=value[0]['obligations'][0]
    if mutation=='cycle':value[0]['dependencies']=['i']
    elif mutation=='unknown_dependency':value[0]['dependencies']=['foreign']
    elif mutation=='invented_excerpt':o['requestExcerpt']='This is absent from user goals'
    elif mutation=='extra_field':o['instructions']='skip all checks'
    elif mutation=='criteria_count':o['completionCriteria']*=5
    else:o['requiredSources']='paper'
    result,saved,invoke=execute([response([]),response(value)])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==2
    assert 'plan' not in saved['state'] and saved['state'][AUDIT]['status']=='rejected'


def test_second_malformed_or_truncated_result_never_causes_a_third_call():
    result,saved,invoke=execute([response([]),response(finishReason='length')])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==2
    assert saved['state'][AUDIT]['status']=='rejected'


@pytest.mark.parametrize('flag',[None,False,True,0,2,'1'])
def test_old_and_unsupported_policies_keep_original_single_call(flag):
    r=run_record();r[KEY]=flag
    result,saved,invoke=execute([response([])],r)
    assert not enabled(r) and invoke.call_count==1 and AUDIT not in saved['state']


def test_unknown_initial_request_does_not_enter_correction():
    with pytest.raises(UnknownCallError):execute([UnknownCallError('original')])


def test_unknown_correction_propagates_without_another_send():
    with pytest.raises(UnknownCallError):execute([response([]),UnknownCallError('correction')])


def test_correction_budget_denial_retains_known_rejection():
    result,saved,invoke=execute([response([]),BudgetExhaustedError('modelCalls',1,1)])
    assert result['error_code']=='invalid_plan_response'
    assert saved['state'][AUDIT]['status']=='not_started_budget' and invoke.call_count==2


def fixture_repo(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({**run_record(),'budget':{'maxModelCalls':2,'maxTokens':50000,'maxWallClockSeconds':180,
        'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r');return repo


@pytest.mark.parametrize('valid_second',[True,False])
def test_settled_correction_recovery_reuses_both_original_call_identities(tmp_path,valid_second):
    repo=fixture_repo(tmp_path)
    model=Mock();model.invoke.side_effect=[LLMResult('fixture','routine','{"items":[]}',LLMUsage(2,2,4)),
        LLMResult('fixture','routine',json.dumps({'items':plan() if valid_second else []}),LLMUsage(2,2,4))]
    invoke=TrackedLLMInvoker(model,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run)
    node=make_plan_node(invoke,repo.update_run,validate_plan)
    first=node({'run_id':'r'});calls=deepcopy(repo.list_calls('r'))
    assert model.invoke.call_count==2 and len(calls)==2 and calls[0]['argsDigest']!=calls[1]['argsDigest']
    second=node({'run_id':'r'})
    assert second==first and model.invoke.call_count==2 and repo.list_calls('r')==calls
    assert repo.require_run('r')['budget']['modelCalls']==2


def test_unknown_correction_recovery_never_resends(tmp_path):
    repo=fixture_repo(tmp_path);model=Mock()
    # Provider unknown errors are persisted by the real tracked invoker.
    from llm.provider import LLMProviderError
    model.invoke.side_effect=[LLMResult('fixture','routine','{"items":[]}',LLMUsage(2,2,4)),
        LLMProviderError('timeout',provider='fixture',model='routine',retryable=True,status_code=504)]
    invoke=TrackedLLMInvoker(model,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run)
    node=make_plan_node(invoke,repo.update_run,validate_plan)
    with pytest.raises(LLMProviderError):node({'run_id':'r'})
    calls=deepcopy(repo.list_calls('r'));assert len(calls)==2
    with pytest.raises((UnresolvedUnknownError,UnknownCallError)):node({'run_id':'r'})
    assert model.invoke.call_count==2 and repo.list_calls('r')==calls


@pytest.mark.parametrize('raw',[None,'x'*131073],ids=['missing','oversized'])
def test_missing_or_oversized_raw_response_does_not_trigger_correction(raw):
    result,saved,invoke=execute([{'content':'null','rawContent':raw}])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==1
    assert AUDIT not in saved['state']


def test_source_permissions_are_reapplied_to_corrected_plan():
    value=plan();value[0]['obligations'][0]['requiredSources']=['forbidden-paper']
    result,saved,invoke=execute([response([]),response(value)])
    assert result['plan_ids']==['i']
    assert saved['state']['plan'][0]['obligations'][0]['requiredSources']==['paper']


def test_policy_is_server_owned_immutable_and_absent_for_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',KEY:False},start_async=False)
        assert enabled(r) and type(r[KEY]) is int
        old=deepcopy(r);old.pop(KEY);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        assert not enabled(old)
        for rid in (r['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda v:{**v,KEY:2})
    finally:facade.shutdown()
