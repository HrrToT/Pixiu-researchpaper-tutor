from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.scope_evidence import include_scope_evidence,condition_score
from services.deep_research.contracts import DeepResearchError


def row(index,text,*,owner='p',version='a'*16,**extra):
    return {'sourceId':f'{owner}-v{version}-chunk-{index}','pdfId':owner,'sourceType':'current_paper',
            'text':f'Paper: Actual paper\n\nSection: Results\n\nContent:\n{text}',
            'retrievalMode':'indexed_hybrid','location':{'chunk':index,'section':'Results'},
            'metadata':{'id':owner,'index_version':version,'chunk_index':index,'section_title':'Results'},**extra}


def record():
    return {'scopeEvidenceContractVersion':1,'state':{'plan':[{'obligations':[{
        'obligationId':'o','question':'报告结果及成立条件和未验证范围','searchQuery':'method quality PSNR conditions',
        'requiredSources':['p'],'completionCriteria':[{'requirement':'成立条件','responseType':'limitation'}]}]}]}}


def fixture():
    selected=[row(0,'Main reported result.'),row(1,'Main table.',tableData={'rows':['original']}),
              row(2,'Other original table.',tableData={'rows':['original']}),row(3,'Generic summary.'),row(4,'Another overview.')]
    detail=row(32,'Sensitivity analysis: at a parameter value of 12, error was low. '
                  'When the parameter reached 28, error increased.')
    return selected,detail


def test_condition_passage_uses_original_slots_preserving_main_results_tables_and_identity():
    selected,detail=fixture();before=deepcopy((selected,detail))
    found=include_scope_evidence(selected,[*selected,detail],record(),'method quality PSNR conditions','p',5)
    assert [r['sourceId'] for r in found]==[r['sourceId'] for r in selected[:4]]+[detail['sourceId']]
    assert len(found)==5 and found[-1]['text']==detail['text'] and found[-1]['metadata']==detail['metadata']
    assert found[-1]['retrievalMode']=='indexed_scope_condition' and (selected,detail)==before
    assert include_scope_evidence(found,[*selected,detail],record(),'method quality PSNR conditions','p',5)==found


@pytest.mark.parametrize('marker',[None,0,True,'1',2])
def test_legacy_or_invalid_policy_does_not_change_selection(marker):
    selected,detail=fixture();r=record();r['scopeEvidenceContractVersion']=marker
    assert include_scope_evidence(selected,[detail],r,'method quality PSNR conditions','p',5)==selected


@pytest.mark.parametrize('mutation',['foreign','version','restricted','ambiguous_chunk','bad_id','wrong_location'])
def test_mixed_owner_version_or_ambiguous_identity_cannot_enter_selection(mutation):
    selected,detail=fixture();pool=[detail]
    if mutation=='foreign':pool=[row(32,detail['text'],owner='foreign')]
    elif mutation=='version':pool=[row(32,detail['text'],version='b'*16)]
    elif mutation=='restricted':pool[0]={**detail,'accessLevel':'abstract'}
    elif mutation=='ambiguous_chunk':pool.append({**detail,'text':'Different text for same identity'})
    elif mutation=='bad_id':pool[0]={**detail,'sourceId':'misleading-id'}
    else:pool[0]={**detail,'location':{'chunk':1,'section':'Results'}}
    assert include_scope_evidence(selected,pool,record(),'method quality PSNR conditions','p',5)==selected


def test_unrelated_query_or_source_permission_does_not_grant_condition_coverage():
    selected,detail=fixture();r=record()
    assert include_scope_evidence(selected,[detail],r,'unrelated search','p',5)==selected
    r['state']['plan'][0]['obligations'][0]['requiredSources']=['foreign']
    assert include_scope_evidence(selected,[detail],r,'method quality PSNR conditions','p',5)==selected


def test_all_protected_slots_and_complete_context_pairs_remain_intact():
    selected,detail=fixture()
    selected[3].update(retrievalMode='indexed_preceding_context',contextForSourceId=selected[4]['sourceId'])
    selected[4]['retrievalMode']='indexed_requested_row'
    assert include_scope_evidence(selected,[detail],record(),'method quality PSNR conditions','p',5)==selected
    assert include_scope_evidence(selected,[detail],record(),'method quality PSNR conditions','p',1)==selected[:1]


def test_body_scoring_is_domain_neutral_and_does_not_use_headers_or_table_row_numbers():
    assert condition_score(row(8,'At temperature 15 the yield was high. Under temperature 35 the yield declined.'))>(0,0,0)
    decoy=row(9,'General overview without tested conditions.')
    decoy['text']='Paper: Sensitivity at 12 quality decreased\n\nSection: at 28 error increased\n\nContent:\nGeneral overview.'
    assert condition_score(decoy)==(0,0,0)
    assert condition_score(row(10,'Table row 12: error at 28 | 14'))==(0,0,0)
    assert condition_score(row(11,'An ablation study is discussed elsewhere.'))==(0,0,0)


def test_pdf_fallback_requires_exact_hash_version_and_fulltext():
    selected,detail=fixture()
    def pdf(item):
        return {k:v for k,v in {**item,'sourceId':'src-'+item['sourceId'],'contentHash':'hash',
                               'versionId':'version','accessLevel':'fulltext','retrievalMode':'pdf_lexical_fallback'}.items() if k!='metadata'}
    selected=[pdf(r) for r in selected];detail=pdf(detail)
    found=include_scope_evidence(selected,[detail],record(),'method quality PSNR conditions','p',5,content_hash='hash')
    assert found[-1]['sourceId']==detail['sourceId'] and found[-1]['retrievalMode']=='pdf_scope_condition'
    assert include_scope_evidence(selected,[{**detail,'contentHash':'changed'}],record(),
                                  'method quality PSNR conditions','p',5,content_hash='hash')==selected


def test_new_flag_is_server_owned_immutable_and_legacy_runs_are_not_upgraded(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'run.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'条件','deferStart':True,
                            'scopeEvidenceContractVersion':0},start_async=False)
        assert run['scopeEvidenceContractVersion']==1
        for replacement in (0,True,'1',None,2):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run['runId'],lambda r:{**r,'scopeEvidenceContractVersion':replacement})
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('scopeEvidenceContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'继续','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()


def test_real_local_adapter_retains_late_condition_passage_even_for_metric_queries(monkeypatch):
    from test_deep_research_local_sources import fixture as local_fixture
    from services.tools import retrieval_tools
    local,get,parse,validate=local_fixture(monkeypatch)
    saved=local.repo.require_run.return_value
    saved.update(record());saved['sourcePrecisionContractVersion']=3
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def doc(i,text):
        return {'text':text,'metadata':{'id':'p','index_version':'a'*16,'chunk_index':i,'section_title':'Results'}}
    indexed=[doc(i,'Reported quality overview.') for i in range(5)]
    corpus=[*indexed,*[doc(i,'Other original discussion.') for i in range(5,32)],
            doc(32,'Ablation: at parameter 12 the error is low. When the parameter reaches 28, error increases.')]
    rag=Mock();rag.normalize_id.side_effect=lambda x:x;rag.get_documents_by_metadata.return_value=corpus
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=indexed);monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    # Isolate selection from the existing publication-identity PDF read.
    monkeypatch.setattr(local,'_stamp_identity',lambda rows,_:rows)
    found=local('method quality PSNR conditions','p',limit=5)
    assert len(local.index_context['p'])==33 and 0<len(found)<=5
    assert found[-1]['chunkIndex']==32 and found[-1]['retrievalMode']=='indexed_scope_condition'
    retrieve.assert_called_once_with('method quality PSNR conditions',top_k=8,filter_metadata={'id':'p'},allow_query_rewrite=False)
    get.assert_not_called();parse.assert_not_called()
    validate.return_value=False
    with pytest.raises(DeepResearchError,match='范围已变更'):
        local('method quality PSNR conditions','p',limit=5)


def test_scope_is_rechecked_after_selection_before_any_candidate_is_returned(monkeypatch):
    from test_deep_research_local_sources import fixture as local_fixture
    local,get,parse,validate=local_fixture(monkeypatch)
    local.repo.require_run.return_value.update(record())
    selected,detail=fixture();validate.side_effect=[True,False]
    with pytest.raises(DeepResearchError,match='范围已变更'):
        local._scope_evidence(selected,[detail],'method quality PSNR conditions','p',5)
    get.assert_not_called();parse.assert_not_called()
