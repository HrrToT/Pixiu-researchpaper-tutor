from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.external_sections import spans,select,passages,enabled
from services.deep_research.external import _page_passages,AcademicAcquisition,_reading_terms


def pages():
    return [{'page':1,'text':'1 INTRODUCTION\nOur depth normal maps improve geometry.\n2 RELATED WORK\nPrior methods depth normal geometry. '*20},
            {'page':2,'text':'3 METHOD\n3.1 Representation\nWe retain volumetric kernels.\n3.2 Loss Functions\nWe penalize disagreement between predicted and measured normals. '},
            {'page':3,'text':'The regularizer updates the kernel orientation.\n4 EXPERIMENT\n4.1 Implementation Details. We integrate predicted depths into a volume and extract a mesh.\n4.2 Datasets\nThe dataset contains indoor views.'},
            {'page':4,'text':'REFERENCES\ndepth normal geometry '*50}]


def test_method_request_reads_actual_method_and_implementation_before_keyword_heavy_background():
    original=pages();before=deepcopy(original)
    chosen=select(original,'解释这些图怎样用于重建 depth normal geometry',{'depth','normal','geometry'})
    assert [p['page'] for p,_ in chosen][:2]==[2,3]
    assert len(chosen)==3 and original==before
    assert '3 METHOD / 3.2 Loss Functions' in [part['section'] for part in chosen[1][1]]


def test_requested_related_work_and_reported_results_are_not_forced_into_method_sections():
    from services.deep_research.external_sections import premise_priority
    for q in ('解释相关工作 depth normal geometry','explain reported results depth normal geometry','解释实验结果 depth normal geometry'):
        assert select(pages(),q,{'depth','normal','geometry'})[0][0]['page']==1
        assert premise_priority({'sourceKind':'arxiv','quote':'We construct the model.',
            'location':{'sectionRole':'method'}},q,'')==(0,0,0)
    assert premise_priority({'sourceKind':'arxiv','quote':'We construct the model.',
        'location':{'sectionRole':'method'}},'报告主表的测量结果','')==(0,0,0)


def test_exact_offsets_section_transitions_and_cross_page_context_are_preserved():
    annotated=spans(pages());assert annotated[2][1][0]['section']=='3 METHOD / 3.2 Loss Functions'
    pieces=[]
    for page,parts in annotated:
        for offset,text,section,role in passages(page,parts,_page_passages):
            assert text==page['text'][offset:offset+len(text)]
            pieces.append((text,section,role))
    assert any('extract a mesh' in text and role=='method' and 'Implementation Details' in section for text,section,role in pieces)
    assert any('dataset contains' in text and role=='other' for text,_,role in pieces)
    assert all(not ('RELATED WORK' in section and 'We retain' in text) for text,section,_ in pieces)


def test_page_allowance_and_literal_page_envelope_remain_bounded():
    p={'page':1,'text':'3 METHOD\n'+('We update the state. '*500)}
    page,parts=spans([p])[0];rows=list(passages(page,parts,_page_passages))
    assert sum(len(text) for _,text,_,_ in rows)==6000
    assert all(len(text)<=3000 and offset+len(text)<=6000 for offset,text,_,_ in rows)
    assert len(select(pages(),'how does the method work',set()))==3


def test_layout_hint_is_not_an_invented_method_heading_or_scientific_approval():
    p=[{'page':1,'text':'1 Our method reaches high accuracy.\n2 We compare the method to a baseline.\nThe word method is not a section.'}]
    assert all(part['role']=='unknown' for _,parts in spans(p) for part in parts)
    assert not enabled({'externalReadingContractVersion':True})
    assert not enabled({'externalReadingContractVersion':4})
    assert enabled({'externalReadingContractVersion':3})
    assert enabled({'externalReadingContractVersion':1})


def test_repeated_transform_words_do_not_displace_the_requested_application_step():
    from services.deep_research.external_sections import premise_priority
    repeated={'sourceKind':'arxiv','quote':'We transform the coordinates. This transformation transforms the basis.',
              'location':{'section':'3 Method / 3.2 Coordinates','sectionRole':'method'}}
    execution={'sourceKind':'arxiv','quote':'We construct the output instructions from the intermediate representation.',
               'location':{'section':'4 Evaluation / 4.1 Implementation Details','sectionRole':'method'}}
    before=deepcopy((repeated,execution))
    question='这些表示怎样用于代码生成？'
    assert premise_priority(execution,question,'code generation')>premise_priority(repeated,question,'code generation')
    assert (repeated,execution)==before
    # A derivation is not automatically an application/implementation request.
    assert premise_priority(execution,'如何变换坐标','')[1]==3


def test_author_representation_definition_outranks_front_matter_benefits_for_identity():
    from services.deep_research.external_sections import premise_priority
    caption={'sourceKind':'arxiv','quote':'Our system achieves fast results.','location':{}}
    definition={'sourceKind':'arxiv','quote':'Unlike earlier approaches that reformulate the primitives, our model retains the original representation.','location':{}}
    assert premise_priority(definition,'解释它是否改变了表示','')>premise_priority(caption,'解释它是否改变了表示','')


def test_conceptual_overview_and_derivation_have_distinct_bounded_page_selection():
    p=[{'page':1,'text':'Paper title\nOur representation retains the original primitives.'},
       {'page':2,'text':'2 METHOD\nWe derive coordinates.'},
       {'page':3,'text':'The method computes a gradient.'},
       {'page':4,'text':'The method computes depth.'}]
    conceptual=select(p,'解释方法怎样工作',{'method'})
    assert 1 in [page['page'] for page,_ in conceptual] and len(conceptual)==3
    derivation=select(p,'推导公式 explain equations',{'method'})
    assert 1 not in [page['page'] for page,_ in derivation] and len(derivation)==3


@pytest.mark.parametrize('version',[None,1,2,3])
def test_real_acquisition_protocol_keeps_legacy_locations_and_new_exact_section_slices(tmp_path,version):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research_academic import AcademicSourceClient,AcademicPolicy
    from test_deep_research_exact_discovery import atom
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    record={'runId':'r','taskId':'t','exactDiscoveryContractVersion':1,'sourcePolicy':{'mode':'external_only'}}
    if version:record['externalReadingContractVersion']=version
    repo.create_run(record);repo.begin_execution('r')
    client=AcademicSourceClient(AcademicPolicy(enabled=True,mode='external_only',allow_fulltext=True),lambda *_:('application/atom+xml',atom(['2308.04079v1'])))
    client.fetch_fulltext=Mock(return_value={'workId':'arxiv:2308.04079','versionId':'arxiv:2308.04079v1','arxivId':'2308.04079v1','contentHash':'hash','accessLevel':'fulltext','pages':pages()})
    sources=AcademicAcquisition(repo,repo.complete_call,client_factory=lambda _:client)('r',[
        {'obligationId':'o','question':'解释怎样构建模型','query':'depth normal geometry','requiredSources':['arxiv:2308.04079v1']}])
    for s in sources:
        page=next(p for p in pages() if p['page']==s['location']['page'])
        offset=s['location']['offset'];assert page['text'][offset:offset+len(s['text'])]==s['text']
        assert ('sectionRole' in s['location']) is bool(version)
        assert s['versionId']=='arxiv:2308.04079v1' and s['contentHash']=='hash' and s['obligationIds']==['o']
    if version:assert any('Implementation Details' in s['location']['section'] for s in sources)
    assert len({s['location']['page'] for s in sources})<=3
    client.fetch_fulltext.assert_called_once()
