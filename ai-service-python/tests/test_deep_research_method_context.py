from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.source_continuity import include_method_context,method_reference,needs_preceding_context
from services.deep_research.reading_priority import select_read_sources
from test_deep_research_source_continuity import row as indexed_row


def row(i,text,section='Method'):
    return {**indexed_row(i,text,section=section),'accessLevel':'fulltext','contentHash':f'hash{i}'}


def chain():
    return [row(8,'However, select candidates by the final-epoch gradient and sample their positions.'),
        row(9,'For each selected primitive, copy its scale and appearance; set the stated opacity.'),
        row(10,'After spawning, optimize the new primitives and apply quantity control.')]


@pytest.mark.parametrize('text',['After spawning, fit new states.','For each selected primitive, copy its scale.',
    'Based on these candidates, initialize the added states.','随后优化新状态。'])
def test_only_new_procedural_option_recognizes_step_antecedents(text):
    value=row(10,'Paper: Example\nContent:\n'+text)
    assert method_reference(value) and needs_preceding_context(value,procedural=True)
    assert not needs_preceding_context(value)


def test_complete_two_step_bundle_preserves_best_hit_existing_membership_pair_and_original_values():
    previous,near,anchor=chain();member=row(37,'The scene belongs to this dataset.','Evaluation')
    figure=row(38,'In Fig.6, compare the two methods.','Evaluation')
    member.update(contextForSourceId=figure['sourceId'],retrievalMode='indexed_preceding_context')
    low=row(31,'Another result.');selected=[anchor,low,member,figure];before=deepcopy((selected,previous,near))
    result=include_method_context(selected,[*chain(),member,figure],'paper',5)
    assert [r['location']['chunk'] for r in result]==[8,9,10,37,38]
    for source in (previous,near):
        new=next(r for r in result if r['sourceId']==source['sourceId'])
        assert {k:v for k,v in new.items() if k not in ('contextForSourceId','retrievalMode')}==source
    assert next(r for r in result if r['sourceId']==member['sourceId'])==member
    assert (selected,previous,near)==before


def test_insufficient_capacity_keeps_original_instead_of_displacing_best_or_existing_context():
    previous,near,anchor=chain();best=row(1,'Best semantic match.');member=row(37,'Named scene.','Evaluation')
    figure=row(38,'In Fig.6, compare methods.','Evaluation');member['contextForSourceId']=figure['sourceId']
    selected=[best,anchor,member,figure,row(32,'Lower match.')]
    assert include_method_context(selected,[previous,near],'paper',5)==selected


def test_existing_semantic_predecessor_is_not_relabelled_and_only_missing_prior_is_added():
    previous,near,anchor=chain();before=deepcopy(near)
    result=include_method_context([anchor,near],[previous,near],'paper',3)
    assert [r['location']['chunk'] for r in result]==[8,9,10]
    assert result[1]==before and near==before


@pytest.mark.parametrize('change',['owner','version','section','prefix','chunk_bool','abstract','location','duplicate','unknown_access','unknown_type'])
def test_foreign_ambiguous_inconsistent_or_abstract_predecessor_is_not_borrowed(change):
    previous,near,anchor=chain();candidates=[previous,near]
    if change=='owner':near['pdfId']='other'
    elif change=='version':near['metadata']['index_version']='b'*16
    elif change=='section':near['metadata']['section_title']='Other'
    elif change=='prefix':near['sourceId']='other-v'+'a'*16+'-chunk-9'
    elif change=='chunk_bool':near['metadata']['chunk_index']=True
    elif change=='abstract':near['accessLevel']='abstract'
    elif change=='location':near['location']['chunk']=999
    elif change=='unknown_access':near.pop('accessLevel')
    elif change=='unknown_type':near.pop('accessLevel');near['sourceType']='external_academic'
    else:candidates.append(deepcopy(near))
    assert include_method_context([anchor],candidates,'paper',3)==[anchor]


def readable(item):
    return {**item,'workId':'paper','ownerMaterialId':'paper','versionId':'doc-version','obligationIds':['o']}


def ordered(monkeypatch):
    monkeypatch.setattr('services.deep_research.reading_priority.prioritize_extraction_passages',lambda rows,*_:rows)


def test_reading_gets_all_original_chunks_in_dependency_order_under_same_cap(monkeypatch):
    ordered(monkeypatch);previous,near,anchor=map(readable,chain());sources=[anchor,near,previous]
    obs={'o':{'obligationId':'o','question':'Explain this operation','requiredSources':['paper']}}
    before=deepcopy(sources)
    old=select_read_sources(sources,obs,3,illustrative_context=True)
    new=select_read_sources(sources,obs,3,illustrative_context=True,method_context=True)
    assert [r['location']['chunk'] for r in old]==[10,9,8]
    assert [r['location']['chunk'] for r in new]==[8,9,10] and sources==before
    assert len(select_read_sources(sources,obs,2,method_context=True))<=2


@pytest.mark.parametrize('change',['owner','version','section','missing_owner','abstract','location'])
def test_reader_does_not_merge_wrong_owner_version_section_or_location(monkeypatch,change):
    ordered(monkeypatch);previous,near,anchor=map(readable,chain())
    if change=='owner':near['ownerMaterialId']='other'
    elif change=='version':near['versionId']='different'
    elif change=='section':near['location']['section']='different'
    elif change=='missing_owner':anchor.pop('ownerMaterialId')
    elif change=='abstract':near['accessLevel']='abstract'
    else:near['location']['chunk']=True
    sources=[anchor,near,previous];obs={'o':{'obligationId':'o','requiredSources':['paper']}}
    new=select_read_sources(sources,obs,3,illustrative_context=True,method_context=True)
    assert new[0]['sourceId']==anchor['sourceId']


@pytest.mark.parametrize('version',[1,2])
def test_local_index_path_applies_new_bundle_only_for_new_contract_and_keeps_cache(monkeypatch,version):
    from services.tools import retrieval_tools
    from test_deep_research_local_sources import fixture
    local,*_=fixture(monkeypatch)
    local.repo.require_run.return_value.update(sourcePrecisionContractVersion=8,
        sourceContinuityContractVersion=version,state={'plan':[]})
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def doc(i,text,section='Method'):
        return {'text':text,'metadata':{'id':'p','index_version':'a'*16,'chunk_index':i,'section_title':section,'page':3}}
    anchor=doc(10,'After spawning, optimize these new states.')
    hits=[anchor,doc(31,'Another method result.'),doc(38,'In Fig.6, compare methods.','Evaluation')]
    prior=[doc(8,'However, select high-gradient points and sample positions.'),
        doc(9,'For each selected point, copy scale and appearance.'),doc(37,'The scene belongs to Dataset.','Evaluation')]
    rag=Mock();rag.normalize_id.side_effect=lambda x:x;rag.get_documents_by_metadata.return_value=[*hits,*prior]
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',lambda *_a,**_k:hits)
    monkeypatch.setattr('services.deep_research.method_details.include_method_details',lambda rows,*_a,**_k:rows)
    monkeypatch.setattr('services.deep_research.criterion_sources.include_indexed_criteria',lambda rows,*_a,**_k:rows)
    for _ in range(2):
        result=local('understand full method','p',limit=5)
        chunks=[r['location']['chunk'] for r in result]
        assert len(chunks)<=5 and 10 in chunks and 37 in chunks and 38 in chunks
        assert (8 in chunks and 9 in chunks) is (version==2)
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
