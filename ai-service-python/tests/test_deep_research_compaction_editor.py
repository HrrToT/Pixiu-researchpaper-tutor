from copy import deepcopy
import pytest
from services.deep_research.structured_output import messages_for_record
from services.deep_research.compaction_editor import SYSTEM


def record(version=1):
    return {'structuredOutputContractVersion':15,'draftSystemContractVersion':1,
        'compactionEditorContractVersion':version,'state':{'outputKind':'direction_survey'}}


def test_editor_role_replaces_research_repair_only_for_new_compaction():
    prompt='只精简三个原点，300字以内。';r=record();before=deepcopy(r)
    new=messages_for_record(r,'synthesize_compact',prompt)
    old=messages_for_record(record(0),'synthesize_compact',prompt)
    assert new==[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}]
    assert 'Fix ALL checks' in old[0]['content'] and 'Fix ALL checks' not in SYSTEM
    assert 'HARD character allowance' in SYSTEM and len(SYSTEM.encode())+128<=1024
    assert r==before


@pytest.mark.parametrize('node',['synthesize','repair_claims','verify','plan','verify_advice','synthesize_audience'])
def test_other_roles_remain_byte_identical(node):
    assert messages_for_record(record(1),node,'prompt')==messages_for_record(record(0),node,'prompt')


@pytest.mark.parametrize('version',[None,True,0,2,'1'])
def test_noninteger_or_unknown_editor_flag_cannot_select_role(version):
    assert messages_for_record(record(version),'synthesize_compact','p')==messages_for_record(record(0),'synthesize_compact','p')


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_editor_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'说明方法','deferStart':True,
            'compactionEditorContractVersion':replacement},start_async=False)
        assert run['compactionEditorContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'compactionEditorContractVersion':replacement})
    finally:facade.shutdown()
