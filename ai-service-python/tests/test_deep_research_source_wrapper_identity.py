from copy import deepcopy
import pytest
from services.deep_research.source_passages import body_start,owned_wrapper_title
from services.deep_research.contracts import DeepResearchError


def fixture():
    sha='a'*64;work=sha+'.pdf'
    material={'materialId':work,'workId':work,'versionId':sha,'contentHash':sha}
    record={'sourceWrapperIdentityContractVersion':1,'materials':[material]}
    source={'sourceKind':'task_paper','workId':work,'ownerMaterialId':work,
        'versionId':sha,'contentHash':'b'*64,'title':'Readable title.pdf'}
    text=f'Paper: {work}\n\nSection: Methods\n\nContent:\nExact source body.'
    return record,source,{'section':'Methods'},text


def test_exact_material_wrapper_preserves_original_bytes_and_body_offsets():
    record,source,location,text=fixture();before=deepcopy((record,source,text))
    offset=body_start(source,location,text,owned_title=owned_wrapper_title(record,source))
    assert text[offset:]=='Exact source body.'
    assert text[:offset].endswith('Content:\n') and (record,source,text)==before
    with pytest.raises(DeepResearchError):body_start(source,location,text)


@pytest.mark.parametrize('change',['legacy','bool','owner','work','kind','version','hash','material_work','missing','similar_id','section'])
def test_foreign_or_unbound_wrapper_still_fails(change):
    record,source,location,text=fixture()
    if change=='legacy':record.pop('sourceWrapperIdentityContractVersion')
    if change=='bool':record['sourceWrapperIdentityContractVersion']=True
    if change=='owner':source['ownerMaterialId']='foreign'
    if change=='work':source['workId']='foreign'
    if change=='kind':source['sourceKind']='arxiv'
    if change=='version':source['versionId']='old-version'
    if change=='hash':record['materials'][0]['contentHash']='c'*64
    if change=='material_work':record['materials'][0]['workId']='foreign'
    if change=='missing':record['materials']=[]
    if change=='similar_id':text=text.replace('Paper: ','Paper: alias-',1)
    if change=='section':location['section']='Other section'
    with pytest.raises(DeepResearchError):body_start(source,location,text,owned_title=owned_wrapper_title(record,source))


def test_readable_title_and_unwrapped_body_remain_unchanged():
    record,source,location,text=fixture();text=text.replace(source['workId'],source['title'])
    assert text[body_start(source,location,text):]=='Exact source body.'
    assert body_start(source,location,'Raw PDF body.')==0


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_source_wrapper_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释材料','deferStart':True,
            'sourceWrapperIdentityContractVersion':replacement},start_async=False)
        assert run['sourceWrapperIdentityContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'sourceWrapperIdentityContractVersion':replacement})
    finally:facade.shutdown()


def test_owned_wrapper_preserves_multiline_unicode_section_exactly():
    record,source,location,text=fixture();location['section']='方法\n局部条件'
    text=text.replace('Section: Methods','Section: 方法\n局部条件')
    offset=body_start(source,location,text,owned_title=owned_wrapper_title(record,source))
    assert text[offset:]=='Exact source body.' and text[:offset].endswith('Content:\n')
