from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
from services.deep_research.repair import repair_rejected
from services.deep_research.repair_batches import split_repair_targets
from test_deep_research_repair_batches import inputs,fake_preparer,response


OPTIONS={'scheduling_version':1,'shared_experiment_schema':True,'experimental_edits':True}


def test_proven_structural_group_moves_first_without_dropping_or_splitting_targets():
    report,checks=inputs();checks['rejected'][-1].update(reason='incomplete_experiment_workflow',detail='workflow.states.shape')
    legacy=split_repair_targets(report['claims'])
    new=split_repair_targets(report['claims'],structural_priority=True,rejections=checks['rejected'])
    assert new==[legacy[-1],*legacy[:-1]]
    assert sorted(sum(new,[]))==sorted(c['claimId'] for c in report['claims'])
    # A model's prose does not create a server structural failure.
    checks['rejected'][-1]['reason']='semantic_unresolved'
    checks['rejected'][-1]['detail']='incomplete_experiment_workflow'
    assert split_repair_targets(report['claims'],structural_priority=True,rejections=checks['rejected'])==legacy


def test_remaining_budget_can_be_used_on_hard_state_before_soft_data_findings(monkeypatch):
    report,checks=inputs();fake_preparer(monkeypatch);sent=[];states=[]
    checks['rejected'][-1]['reason']='incomplete_experiment_workflow'
    def invoke(prompt):
        sent.append(json.loads(prompt)['targets'])
        if len(sent)>1:raise BudgetExhaustedError('tokens',1,2)
        return response(prompt)
    result=repair_rejected(report,checks,[],'Exact question',invoke,json.loads,checkpoint=states.append,**OPTIONS)
    assert sent[0]==['steps'] and [c['claimId'] for c in result]==['steps']
    assert states[-1]['batches']==[['steps'],['data','budget'],['h','a']]
    assert states[-1]['results']['0'][0]['claimId']=='steps'  # Draft only, not approval.


def test_unbound_review_is_not_a_writable_repair_target_but_its_definition_remains_context(monkeypatch):
    report,checks=inputs();fake_preparer(monkeypatch);before=deepcopy((report,checks));sent=[];states=[]
    checks['rejected'][0]['rejectionAudit']={'bindingState':'invalid','errors':['not_an_absent_schema_field']}
    def invoke(prompt):sent.append(json.loads(prompt));return response(prompt)
    result=repair_rejected(report,checks,[],'Exact question',invoke,json.loads,checkpoint=states.append,**OPTIONS)
    assert 'data' not in [c['claimId'] for c in result]
    assert all('data' not in p['targets'] for p in sent)
    for p in sent:
        context=next(c for c in p['context'] if c['claimId']=='data')
        assert context['text']==report['claims'][0]['text'] and context['reviewContextState']['status']=='unreviewed'
    assert states[-1]['deferredReviewIds']==['data'] and report==before[0]


@pytest.mark.parametrize('execution_state',['not_started','received_invalid'])
def test_priority2_defers_unreviewed_capacity_and_invalid_results_without_losing_definitions(monkeypatch,execution_state):
    report,checks=inputs();fake_preparer(monkeypatch);states=[];sent=[]
    checks['rejected'][0].update(executionState=execution_state,reason='semantic_unresolved',
        detail='Review did not produce a usable judgement.')
    def invoke(prompt):sent.append(json.loads(prompt));return response(prompt)
    result=repair_rejected(report,checks,[],'Exact question',invoke,json.loads,checkpoint=states.append,
        **{**OPTIONS,'scheduling_version':2})
    assert 'data' not in [c['claimId'] for c in result]
    assert states[-1]['deferredReviewIds']==['data']
    assert all(next(c for c in p['context'] if c['claimId']=='data')['reviewContextState']['status']=='unreviewed' for p in sent)


@pytest.mark.parametrize('old,new',[(0,1),(1,0),(1,2),(2,1)])
def test_pending_priority_policy_cannot_change_input_identity_or_resend(monkeypatch,old,new):
    report,checks=inputs();fake_preparer(monkeypatch);states=[];invoke=Mock(side_effect=OSError('unknown'))
    kw={**OPTIONS,'scheduling_version':old}
    with pytest.raises(OSError):repair_rejected(report,checks,[],'Exact question',invoke,json.loads,checkpoint=states.append,**kw)
    saved=deepcopy(states[-1]);invoke.reset_mock();kw['scheduling_version']=new
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,[],'Exact question',invoke,json.loads,batch_state=saved,**kw)
    invoke.assert_not_called();assert states[-1]==saved


@pytest.mark.parametrize('replacement',[None,True,'2',0,1,3])
def test_repair_priority_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize();f=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        c,_=f.create({'workspaceTaskId':'t','operationKey':'k','question':'Experiment','deferStart':True,
            'experimentRepairPriorityContractVersion':replacement},start_async=False)
        assert c['experimentRepairPriorityContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(c['runId'],lambda v:{**v,'experimentRepairPriorityContractVersion':replacement})
    finally:f.shutdown()
