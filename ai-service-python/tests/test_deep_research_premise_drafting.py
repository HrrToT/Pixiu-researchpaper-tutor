from copy import deepcopy
import pytest
from services.deep_research.premise_drafting import enabled,GUIDANCE
from test_deep_research_synthesis_instructions import record
from test_deep_research_factual_prompt import template


@pytest.mark.parametrize('value',[None,True,False,0,2,'1'])
def test_legacy_and_invalid_profiles_keep_exact_original_prompt(value):
    base=record();r={**base,'premiseDraftContractVersion':value}
    assert not enabled(r,'paper_comparison') and template(r)==template(base)


def test_added_guidance_changes_no_frozen_request_data_or_schema():
    base=record();r={**base,'premiseDraftContractVersion':1};before=deepcopy(r)
    old=template(base);new=template(r)
    assert enabled(r,'paper_comparison') and new.count(GUIDANCE)==1
    assert new.replace('\n'+GUIDANCE,'',1)==old
    assert r==before
    assert not enabled(r,'experiment_design')
    r['authoredBodyContractVersion']=0
    assert not enabled(r,'paper_comparison')


def test_profile_is_immutable_server_owned_and_not_added_to_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='premiseDraftContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,key:1})
    finally:facade.shutdown()
