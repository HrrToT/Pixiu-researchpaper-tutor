from copy import deepcopy
import pytest
from services.deep_research.external_sections import spans,select,passages,method_requested
from services.deep_research.external import _page_passages


def pages():
    return [
        {'page':1,'text':'Paper title\nWe propose a planar representation.'},
        {'page':2,'text':'I. INTRODUCTION\nBackground depth geometry.\nII. R ELATED WORK\nPrevious geometry methods.\nIII. P RELIMINARY OF 3D G AUSSIAN SPLATTING\nA Gaussian covariance defines an ellipsoid.'},
        {'page':3,'text':'IV. M ETHOD\nA. Planar-based Representation\nWe compress Gaussians into flat planes.'},
        {'page':4,'text':'Flattening Gaussian: We compress the minimum scale axis.\nB. Depth Rendering\nWe render plane distances and normals.'},
        {'page':5,'text':'V. EXPERIMENTS\nA. Datasets\nThe dataset provides images.\nB. Implementation Details\nWe fuse depths into a volume.'},
        {'page':6,'text':'REFERENCES\nWe reconstruct geometry using another method.'}]


def test_roman_and_letter_outline_keeps_exact_titles_offsets_and_cross_page_parent():
    original=pages();before=deepcopy(original);annotated=spans(original,outline=True)
    assert annotated[3][1][0]['section']=='IV. M ETHOD / A. Planar-based Representation'
    assert annotated[3][1][0]['role']=='method'
    assert any(p['section']=='IV. M ETHOD / B. Depth Rendering' for p in annotated[3][1])
    assert annotated[4][1][0]['section']=='V. EXPERIMENTS' and annotated[4][1][0]['role']=='other'
    assert any(p['role']=='method' and 'Implementation Details' in p['section'] for p in annotated[4][1])
    assert all(p['role']=='references' for p in annotated[5][1])
    assert all(p['role']=='other' for p in annotated[1][1])
    for page,parts in annotated:
        for offset,quote,_,_ in passages(page,parts,_page_passages):
            assert page['text'][offset:offset+len(quote)]==quote
    assert original==before


def test_representation_path_request_reads_method_under_original_three_page_cap():
    query='高斯表示与网格提取路径有什么不同'
    assert not method_requested(query) and method_requested(query,outline=True)
    selected=select(pages(),query,{'gaussian','depth'},contract_version=2)
    assert len(selected)==3 and {3,4}<={p['page'] for p,_ in selected}
    for query in ('解释相关工作中的表示','explain reported results representation','报告实验结果'):
        assert not method_requested(query,outline=True)


def test_math_numbered_sentences_and_unrecognized_body_do_not_become_outline():
    sample=[{'page':1,'text':'I. X = R S S^T\nA. We evaluate the result. It improves accuracy.\nB. '+('Long '*18)+'\nordinary method text'}]
    assert all(p['role']=='unknown' for _,parts in spans(sample,outline=True) for p in parts)


@pytest.mark.parametrize('bad',[True,None,0,3,'2'])
def test_unknown_reading_policy_does_not_silently_change_selection(bad):
    with pytest.raises(ValueError):select(pages(),'表示',set(),contract_version=bad)


def test_old_default_outline_and_selection_stay_unextended():
    assert spans(pages())==spans(pages(),outline=False)
    assert all(p['role']!='method' for _,parts in spans(pages()) for p in parts)
    assert select(pages(),'表示',set())==select(pages(),'表示',set(),contract_version=1)

@pytest.mark.parametrize('client_value',[None,True,1,3])
def test_outline_policy_is_server_owned_and_old_runs_stay_frozen(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'表示',
            'deferStart':True,'externalReadingContractVersion':client_value},start_async=False)
        assert record['externalReadingContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'externalReadingContractVersion':client_value})
        old=deepcopy(record);old.update(runId='legacy',idempotencyKey='old',externalReadingContractVersion=1)
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'表示','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
    finally:facade.shutdown()
