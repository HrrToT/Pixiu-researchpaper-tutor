from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.facade import ResearchFacade
from services.deep_research.named_source_rows import include_requested_rows
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.requested_table_rows import requested_table_row_spans, requested_table_row_labels
from services.deep_research.verification import make_evidence, verify_claims
from test_deep_research_named_source_rows import row


TABLE='Table caption: Quality on Dataset A.\nTable row 1: 3D-GS [16] | 12\nTable row 2: 3D-GS * [16] | 14\n'


def test_bibliography_and_cosmetic_method_spelling_preserve_literal_row_and_variant():
    spans=requested_table_row_spans(TABLE,'Compare original 3DGS.',symbol_identity=True)
    assert len(spans)==1 and spans[0] in TABLE and spans[0].endswith('3D-GS [16] | 12')
    assert requested_table_row_labels(TABLE,'Compare original 3DGS.',symbol_identity=True)==['3D-GS [16]']
    assert requested_table_row_spans(TABLE,'Compare original 3DGS.')==[]
    assert requested_table_row_labels(TABLE,'Compare 3DGS*.',symbol_identity=True)==['3D-GS * [16]']
    for text in ('3DGS-finetuned','Other3DGS','3DGS_extra'):
        assert requested_table_row_labels(TABLE,text,symbol_identity=True)==[]


def test_direct_literal_target_ranks_ahead_of_a_cosmetic_search_alias():
    text='Table caption: Results.\nTable row 1: A-B | 12\nTable row 2: AB | 14\n'
    spans=requested_table_row_spans(text,'Compare AB',symbol_identity=True,max_items=1)
    assert len(spans)==1 and spans[0].endswith('AB | 14')


def test_same_capacity_owner_version_and_context_rules_still_apply_to_method_search_aliases():
    top,low=row('top','Method overview'),row('low','Generic evaluation')
    target=row('target',TABLE);before=deepcopy(target)
    result=include_requested_rows([top,low],[target],'Compare 3DGS','paper',2,symbol_identity=True)
    assert [r['sourceId'] for r in result]==['top','target'] and result[-1]['text']==TABLE
    assert result[-1]['contentHash']==target['contentHash'] and target==before
    for field,value in [('pdfId','foreign'),('metadata',{'id':'paper','index_version':'b'*16})]:
        invalid={**target,field:value}
        assert include_requested_rows([top,low],[invalid],'3DGS','paper',2,symbol_identity=True)==[top,low]
    assert include_requested_rows([top],[target],'3DGS','paper',1,symbol_identity=True)==[top]


def test_actual_index_route_uses_human_baseline_instead_of_a_guessed_starred_search_term(monkeypatch):
    from services.tools import retrieval_tools
    from test_deep_research_local_sources import fixture
    local,get,parse,_=fixture(monkeypatch)
    local.repo.require_run.return_value.update(namedRowIdentityContractVersion=1,question='Compare original 3DGS')
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def document(index,text):
        return {'text':text,'metadata':{'id':'p','chunk_index':index,'index_version':'a'*16,'page':4}}
    top=document(0,'Method overview')
    star=document(1,'Table caption: Dataset A.\nTable row 2: 3D-GS * [16] | 14')
    original=document(2,'Table caption: Dataset A.\nTable row 1: 3D-GS [16] | 12')
    rag=Mock();rag.normalize_id.side_effect=lambda v:v;rag.get_documents_by_metadata.return_value=[star,original]
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=[top,star]);monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    found=local('Evaluate 3D-GS * [16] PSNR','p',limit=2)
    assert [r['chunkIndex'] for r in found]==[0,2]
    assert found[-1]['text']==original['text'] and found[-1]['retrievalMode']=='indexed_requested_row'
    retrieve.assert_called_once();get.assert_not_called();parse.assert_not_called()


def test_named_method_retention_is_not_numeric_approval(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    reads=[{'sourceId':'s0','workId':'p0','versionId':'v0','contentHash':'h0',
        'accessLevel':'fulltext','location':{'page':2},'obligationIds':['o'],
        'pages':[{'text':TABLE}]}]
    repo.create_run({'runId':'r','taskId':'t','namedRowIdentityContractVersion':1,
        'question':'Compare 3DGS','state':{'readResults':reads,'plan':[{'itemId':'p',
        'question':'Compare','obligations':[{'obligationId':'o','question':'Compare 3DGS'}]}]}})
    repo.begin_execution('r')
    make_batched_extract_node(Mock(return_value={'content':'[]'}),make_evidence,lambda *a:True,repo.update_run)({'run_id':'r'})
    evidence=repo.require_run('r')['state']['evidence']
    assert evidence and evidence[0]['quote'] in TABLE
    c={'claimId':'c','kind':'reported','text':'3D-GS PSNR 12','evidenceRefs':[evidence[0]['evidenceId']]}
    assert not verify_claims([c],evidence,lambda *a:[{'claimId':'c','status':'passed'}])['accepted']


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_symbolic_search_hint_is_server_owned_and_frozen(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Compare methods',
            'namedRowIdentityContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['namedRowIdentityContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'namedRowIdentityContractVersion':replacement})
    finally:facade.shutdown()
