import pytest
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository


@pytest.mark.parametrize('replacement',[None,True,0,1,2,'3'])
def test_new_priority_is_server_owned_and_all_saved_priority_versions_are_frozen(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释机制',
            'extractionPriorityVersion':replacement,'deferStart':True},start_async=False)
        assert run['extractionPriorityVersion']==3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'extractionPriorityVersion':replacement})
        repo.create_run({'runId':'old','taskId':'t','extractionPriorityVersion':2})
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda r:{**r,'extractionPriorityVersion':3})
        assert repo.require_run('old')['extractionPriorityVersion']==2
    finally:facade.shutdown()
