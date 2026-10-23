from copy import deepcopy
import pytest

from services.deep_research.extraction_schedule import defer_assessment
from services.deep_research.adaptive_assessment import _input_limit
from services.deep_research.extraction import _input_capacity
from services.deep_research.contracts import BudgetExhaustedError,check_exploration_headroom
from services.deep_research.repair_budget import repair_exploration_headroom,repair_prompt_byte_limit
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_joint_assessment import fixture,Memory,execute,ready_response


def budget(**changes):
    return {'maxTokens':100000,'reserveTokens':50000,'maxModelCalls':18,
            'reserveModelCalls':5,'tokens':8577,'normalTokens':8577,
            'modelCalls':4,'explorationAllocationVersion':1,**changes}


def test_observed_comparison_headroom_retains_acquisition_without_widening_total_limits():
    value=budget();old={k:v for k,v in value.items() if k!='explorationAllocationVersion'}
    assert repair_exploration_headroom(50000)==33216
    assert repair_exploration_headroom(50000,1)==20000
    assert _input_capacity(value)==17399 and _input_capacity(old)==4183
    assert _input_limit(value)==18863 and _input_limit(old)==5647
    # Same whole 13000-token envelope fits the new allocation, not the old.
    proposed={**value,'tokens':21577,'normalTokens':21577,'modelCalls':5}
    assert check_exploration_headroom(proposed,'extract') is None
    assert check_exploration_headroom({**proposed,'explorationAllocationVersion':0},'extract')[0]=='explorationTokens'
    assert check_exploration_headroom({**value,'normalTokens':30001},'extract')[0]=='explorationTokens'
    assert repair_prompt_byte_limit(budget(tokens=99000))==0
    assert value==budget()


@pytest.mark.parametrize('value',[None,0,True,'1',2])
def test_unknown_or_forged_allocation_retains_the_legacy_policy(value):
    assert repair_exploration_headroom(50000,value)==33216


def test_deferred_readiness_does_not_grant_coverage_or_spend_requery_round():
    record=fixture();record['extractionScheduleContractVersion']=1
    memory=Memory(record);before=deepcopy(record['state']['evidence'])
    result=defer_assessment({'run_id':'r','extraction_pending':True,'requery_count':1},record,memory.update)
    assert result['gaps'] and all(g['checked'] is False for g in result['gaps'])
    assert result['requery_count']==1 and result['requery_queries']==[]
    assert memory.record['state']['assessmentStatus']=='deferred'
    assert 'coverage' not in memory.record['state'] and memory.record['state']['evidence']==before


@pytest.mark.parametrize('marker,pending,exhausted',[(0,True,False),(True,True,False),('1',True,False),(1,False,False),(1,True,True)])
def test_legacy_finished_or_exhausted_frontier_does_not_defer(marker,pending,exhausted):
    record=fixture();record['extractionScheduleContractVersion']=marker
    assert defer_assessment({'run_id':'r','extraction_pending':pending,'budget_exhausted':exhausted},record,
                            lambda *_a,**_kw:pytest.fail('Do not mutate')) is None


def test_partial_joint_review_cannot_label_all_criteria_checked(monkeypatch):
    record=fixture();record['extractionScheduleContractVersion']=1
    extra=deepcopy(record['state']['plan'][0]['obligations'][0])
    extra.update(obligationId='second',question='Another requested dimension',requestExcerpt='Another dimension')
    extra['completionCriteria'][0]['requirement']='A different requested criterion'
    record['state']['plan'][0]['obligations'].append(extra)
    import services.deep_research.joint_assessment as joint
    real_render=joint._render
    def bounded_render(units,rows,human):
        return real_render(units,rows,human) if len(units)<=1 else 'x'*24001
    monkeypatch.setattr(joint,'_render',bounded_render)
    memory=Memory(record);result=execute(memory,lambda r,n,p,o:ready_response(p))
    assert result['gaps'] and memory.record['state']['assessmentStatus']=='unchecked'
    assert any(row['state']=='supported' for row in memory.record['state']['coverage'])
    assert any(row['checked'] is False for row in memory.record['state']['coverage'])


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_server_policy_is_frozen_and_clients_cannot_retarget_unknown_requests(tmp_path,replacement):
    repo=DeepResearchRepository(str(tmp_path/'r.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Compare',
            'deferStart':True,'extractionScheduleContractVersion':replacement,
            'budget':{'explorationAllocationVersion':replacement}},start_async=False)
        assert run['extractionScheduleContractVersion']==1
        assert run['budget']['explorationAllocationVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'extractionScheduleContractVersion':replacement})
        with pytest.raises(ValueError,match='Immutable budget'):
            repo.update_run(run['runId'],lambda r:{**r,'budget':{**r['budget'],'explorationAllocationVersion':replacement}})
    finally:
        facade.shutdown()


def test_atomic_reservation_still_stops_at_normal_and_total_limits_without_a_provider(tmp_path):
    repo=DeepResearchRepository(str(tmp_path/'r.sqlite3'));repo.initialize()
    repo.create_run({'runId':'r','status':'running','budget':budget()})
    repo.reserve_call(run_id='r',node='extract',tool='llm_invoke',args_digest='new',
                      budget_delta={'modelCalls':1,'tokens':13000})
    assert repo.require_run('r')['budget']['normalTokens']==21577
    with pytest.raises(BudgetExhaustedError):
        repo.reserve_call(run_id='r',node='extract',tool='llm_invoke',args_digest='too-large',
                          budget_delta={'modelCalls':1,'tokens':9000})
    assert repo.require_run('r')['budget']['normalTokens']==21577
    with pytest.raises(BudgetExhaustedError):
        repo.reserve_call(run_id='r',node='repair_claims',tool='llm_invoke',args_digest='total',
                          budget_delta={'modelCalls':1,'tokens':80000})
    assert repo.require_run('r')['budget']['maxTokens']==100000
