from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.table_identity_context import include_context,enabled,GUIDANCE


def fixture():
    def row(i,text,table=False):
        return {'sourceId':'s'+str(i),'text':text,'retrievalMode':'indexed_hybrid',
            'location':{'page':4,'section':'Table 3 :','chunk':i},
            'metadata':{'id':'paper','index_version':'a'*16,'text_source':'pdf_page_text','body_extraction_version':1},
            **({'tableData':{'groups':[['Test',['SSIM']]],'rows':[[1,'Base *',['.8']],[2,'Ours',['.7']]]}} if table else {})}
    table=row(1,'Table row 1: Base * | .8',True)
    primary=row(0,'Main result overview.');filler=row(2,'Optional background.')
    note=row(10,'Table 3: Original experiments. * denotes a re-trained baseline, using original code.')
    return [primary,table,filler],note


def test_actual_note_is_separate_source_not_an_assumed_marker_meaning():
    rows,note=fixture();before=deepcopy((rows,note))
    out=include_context(rows,[note],'paper',3)
    assert [r['sourceId'] for r in out]==['s0','s1','s10']
    assert (rows,note)==before and out[-1] is note
    assert 'tableData' not in out[-1]
    # The selector must work even when a marker explicitly means something else.
    note['text']='Table 3: * denotes the frozen ablation variant, not re-training.'
    assert include_context(rows,[note],'paper',3)[-1]['text']==note['text']


@pytest.mark.parametrize('change',[
    'owner','index','page','different_table','no_marker','tei','not_canonical','no_note',
])
def test_missing_or_mismatched_note_cannot_be_attached(change):
    rows,note=fixture()
    if change=='owner':note['metadata']['id']='foreign'
    elif change=='index':note['metadata']['index_version']='b'*16
    elif change=='page':note['location']['page']=5
    elif change=='different_table':note['text']=note['text'].replace('Table 3:','Table 30:')
    elif change=='no_marker':note['text']=note['text'].replace('*','')
    elif change=='tei':note['metadata']['text_source']='grobid_table'
    elif change=='not_canonical':note['metadata']['body_extraction_version']=None
    else:note['text']='Table 3: Base * and Ours measured SSIM.'
    assert include_context(rows,[note],'paper',3)==rows


def test_no_extra_slot_or_displacement_of_tables_primary_or_condition_evidence():
    rows,note=fixture();rows[-1]['retrievalMode']='indexed_scope_condition'
    assert include_context(rows,[note],'paper',3)==rows
    assert include_context(rows[:1],[note],'paper',1)==rows[:1]
    rows[-1]['tableData']=deepcopy(rows[1]['tableData'])
    assert include_context(rows,[note],'paper',3)==rows
    assert len(include_context(rows,[note],'paper',4))==4
    assert include_context(rows+[note],[note],'paper',4)==rows+[note]


def test_actual_adapter_adds_note_only_for_new_policy_and_rechecks_scope(monkeypatch):
    from test_deep_research_local_sources import fixture as local_fixture
    from services.deep_research.contracts import DeepResearchError
    local,get,parse,validate=local_fixture(monkeypatch)
    local.repo.require_run.return_value.update(scopeEvidenceContractVersion=1,tableIdentityContextContractVersion=1)
    rows,note=fixture()
    found=local._scope_evidence(rows,[note],'quality','paper',3)
    assert found[-1]==note
    local.repo.require_run.return_value.pop('tableIdentityContextContractVersion')
    assert local._scope_evidence(rows,[note],'quality','paper',3)==rows
    local.repo.require_run.return_value['tableIdentityContextContractVersion']=1
    validate.side_effect=[True,False]
    with pytest.raises(DeepResearchError):local._scope_evidence(rows,[note],'quality','paper',3)
    get.assert_not_called();parse.assert_not_called()


def test_generation_and_compact_repair_both_keep_method_identity_guidance():
    from services.deep_research.factual_template import build
    from test_deep_research_compact_source_repair import prepare
    legacy=build({},'核查','claim_verification',300,2,[],[],{},'EVIDENCE','TABLES')
    current=build({'tableIdentityContextContractVersion':1},'核查','claim_verification',300,2,[],[],{},'EVIDENCE','TABLES')
    assert GUIDANCE not in legacy and GUIDANCE in current
    # Compact repair previously replaced an earlier template and lost its rules.
    assert GUIDANCE in prepare(table_identity_context=True)['prompt']
    assert GUIDANCE not in prepare()['prompt']


@pytest.mark.parametrize('replacement',[None,True,0,'1',2])
def test_identity_policy_is_frozen_server_owned_and_absent_from_old_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'tableIdentityContextContractVersion':replacement},start_async=False)
        assert enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'tableIdentityContextContractVersion':replacement})
        legacy=deepcopy(run);legacy.update(runId='legacy',idempotencyKey='legacy');legacy.pop('tableIdentityContextContractVersion')
        repo.create_run(legacy);before=repo.require_run('legacy')
        assert not enabled(before)
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'继续','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
    finally:facade.shutdown()
