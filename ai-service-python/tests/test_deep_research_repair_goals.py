from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair_goals import bind
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_redraft import inputs


def options(requirements):
    return dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,
                compact_source_repair=True,factual_scope=3,requirement_context=requirements)


def test_goal_ownership_is_explicit_without_changing_question_evidence_or_permissions():
    c,e,checks,requirements=inputs();other={'obligationId':'other','question':'Explain an unrelated constraint'}
    all_requirements=requirements+[other];before=deepcopy((c,e,checks,all_requirements))
    kwargs=options(all_requirements)
    old=_prepare_repair({'claims':[c]},checks,[e],'Explain outputs and other constraints',**kwargs)
    new=_prepare_repair({'claims':[c]},checks,[e],'Explain outputs and other constraints',target_goals=True,**kwargs)
    assert 'Frozen goal IDs by target: {"c":["o"]}' in new['prompt']
    assert 'Each rejected target answers ONLY its bound frozen goals' in new['prompt']
    assert 'Frozen goal IDs by target:' not in old['prompt']
    assert new['allowed']==old['allowed'] and new['originals']==old['originals']
    assert e['quote'] in new['prompt'] and 'Explain the output roles' in new['prompt']
    assert (c,e,checks,all_requirements)==before


def test_shared_goals_are_allowed_but_unbound_or_ambiguous_goals_are_not_guessed():
    c,_,_,requirements=inputs();second={**c,'claimId':'second'}
    assert bind([c,second],requirements)=={'c':['o'],'second':['o']}
    for ids in [None,[],['foreign'],['o','o'],[True]]:
        with pytest.raises(ValueError):bind([{**c,'obligationIds':ids}],requirements)
    with pytest.raises(ValueError):bind([c],requirements*2)
    with pytest.raises(ValueError):bind([c],[{'obligationId':[]}])


def test_pending_old_goal_contract_is_not_reinterpreted_or_sent_again():
    c,e,checks,requirements=inputs();states=[]
    class Unknown(Exception):pass
    def invoke(_):raise Unknown()
    with pytest.raises(Unknown):
        repair_rejected({'claims':[c]},checks,[e],'Explain',invoke,json.loads,
            checkpoint=lambda s:states.append(deepcopy(s)),**options(requirements))
    assert states[-1].get('pending')
    send=Mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected({'claims':[c]},checks,[e],'Explain',send,json.loads,
            batch_state=states[-1],target_goals=True,**options(requirements))
    send.assert_not_called()


def test_unbound_target_is_omitted_before_any_provider_dispatch():
    c,e,checks,requirements=inputs();c.pop('obligationIds');send=Mock()
    assert repair_rejected({'claims':[c]},checks,[e],'Explain',send,json.loads,
        target_goals=True,**options(requirements))==[]
    send.assert_not_called()


@pytest.mark.parametrize('field',['factualRepairGoalContractVersion','answerCoherenceContractVersion'])
def test_new_policies_are_server_owned_and_frozen(tmp_path,field):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',
            'deferStart':True,field:False},start_async=False)
        expected=3 if field=='factualRepairGoalContractVersion' else 2
        assert record[field]==expected and type(record[field]) is int
        for value in [None,True,0,4]:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(record['runId'],lambda r:{**r,field:value})
    finally:facade.shutdown()
