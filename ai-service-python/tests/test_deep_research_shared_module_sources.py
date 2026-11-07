from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.shared_modules import named_modules, definition_score
from services.deep_research.criterion_sources import acquisition_modules, include_indexed_criteria, include_pdf_criteria
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.dataset_membership import table_spans
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.synthesis_evidence import order_premises
from services.deep_research.verification import make_evidence
from test_deep_research_method_details import passage
from test_deep_research_local_sources import fixture as local_fixture

QUESTION='固定相同第0帧模型、相机划分及第1阶段TMC结果，两组跳过或执行第2阶段。只选一个场景。'
DEFINITION='TMC encodes positions with a hash network and predicts translation and quaternion rotation outputs using an MLP.'
TABLE='Table caption: Quantitative comparison across all scenes in the Example dataset.\nTable row 1: Method | Coffee Martini Spinach Beef Salmon [cols=5, rows=1]'


def obligation():
    return {'obligationId':'o','question':QUESTION,'searchQuery':'phase two adaptive addition',
        'requiredSources':['p'],'completionCriteria':[{'criterionId':'method','requirement':'核对第2阶段的操作',
                                                       'responseType':'explanation'}]}


@pytest.mark.parametrize('question,expected',[
    (QUESTION,['TMC']),('固定相同PSNR、FPS、GPU和PDF。',[]),
    ('Explain TMC output.',[]),('Compare PaperTMC and another model.',[]),
    ('Keep the same ABC initialization and shared DEF output.',['ABC','DEF']),
    ('固定ABC、DEF和GHI结果。',['ABC','DEF'])])
def test_only_explicit_shared_names_are_bounded_hints(question,expected):
    assert named_modules(question)==expected


def test_matching_human_source_and_obligation_are_all_required_for_acquisition():
    o=obligation();record={'question':QUESTION,'state':{'plan':[{'obligations':[o]}]}}
    before=deepcopy(record)
    assert acquisition_modules(record,o['searchQuery'],'p')==['TMC']
    assert acquisition_modules(record,o['searchQuery'],'foreign')==[]
    assert acquisition_modules(record,'other','p')==[]
    assert acquisition_modules({**record,'question':'解释第2阶段'},o['searchQuery'],'p')==[]
    assert record==before


@pytest.mark.parametrize('variant',['foreign','version','duplicate','title_only'])
def test_definition_acquisition_rejects_foreign_ambiguous_or_wrapper_only_hits(variant):
    selected=[passage(i,'Generic overview.') for i in range(5)]
    detail=passage(21,DEFINITION)
    candidates=[detail]
    if variant=='foreign': candidates=[passage(21,DEFINITION,owner='other')]
    if variant=='version': candidates=[passage(21,DEFINITION,version='b'*16)]
    if variant=='duplicate': candidates=[detail,deepcopy(detail)]
    if variant=='title_only': candidates=[passage(21,'An unrelated network outputs values.')]
    assert include_indexed_criteria(selected,candidates,[],'p',5,modules=['TMC'])==selected


def test_named_definition_uses_existing_slot_and_preserves_original_text_and_context():
    selected=[passage(i,'Generic overview.') for i in range(5)]
    detail=passage(21,DEFINITION);before=deepcopy((selected,detail))
    found=include_indexed_criteria(selected,[detail],['核对第2阶段操作'],'p',5,modules=['TMC'])
    assert len(found)==5 and found[0]==selected[0]
    assert found[1]['text']==detail['text'] and found[1]['sourceId']==detail['sourceId']
    assert include_indexed_criteria(selected,[detail],[],'p',5)==selected
    assert include_indexed_criteria(selected,[detail],[],'p',1,modules=['TMC'])==selected[:1]
    assert (selected,detail)==before
    assert definition_score('Paper: TMC\nContent: unrelated input outputs','TMC')==0


def test_pdf_definition_stays_same_owned_hash_and_within_limit():
    def row(sid,text,owner='p',hash='h'):
        return {'sourceId':sid,'text':text,'pdfId':owner,'contentHash':hash,'accessLevel':'fulltext'}
    top=row('top','Generic overview.');detail=row('detail',DEFINITION)
    assert include_pdf_criteria([top],[detail,row('foreign',DEFINITION,'q'),row('changed',DEFINITION,hash='bad')],
        [],'p','h',2,modules=['TMC'])==[top,detail]
    assert include_pdf_criteria([top],[detail],[],'p','h',1,modules=['TMC'])==[top]


@pytest.mark.parametrize('precision',[6,7])
def test_production_retriever_uses_cached_owned_definition_without_an_extra_search(monkeypatch,precision):
    from services.tools import retrieval_tools
    local,get,parse,_=local_fixture(monkeypatch)
    local.repo.require_run.return_value.update(question=QUESTION,sourcePrecisionContractVersion=precision,
        state={'plan':[{'obligations':[obligation()]}]})
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def doc(index,text,owner='p'):
        return {'text':text,'metadata':{'id':owner,'index_version':'a'*16,'chunk_index':index,
                                      'section_title':'Neural Cache','page':4}}
    rag=Mock();rag.normalize_id.side_effect=lambda value:value
    rag.get_documents_by_metadata.return_value=[doc(21,DEFINITION),doc(99,DEFINITION,'foreign')]
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=[doc(i,'Generic overview.') for i in range(5)])
    monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    found=local(obligation()['searchQuery'],'p',limit=5)
    assert len(found)<=5 and all(r['pdfId']=='p' for r in found)
    assert (21 in {r['chunkIndex'] for r in found})==(precision==7)
    retrieve.assert_called_once()
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    assert get.call_count==parse.call_count==1


def test_reading_and_synthesis_reserve_definition_without_changing_old_profiles():
    from test_deep_research_reading_priority import source
    from test_deep_research_synthesis_premises import evidence
    o=obligation()
    rows=[source('p',i,'Method','We add noise to the state and update positions for fixed iterations.',('o',)) for i in range(15)]
    definition=source('p',21,'Neural Cache',DEFINITION,('o',));rows.append(definition)
    before=deepcopy((rows,o))
    assert definition not in select_read_sources(rows,{'o':o},12,priority_version=8)
    assert definition in select_read_sources(rows,{'o':o},12,priority_version=9)
    ev=[evidence(str(i),r['text']) for i,r in enumerate(rows)]
    plan=[{'obligations':[o]}]
    old,_=order_premises(ev,plan,limit=4,membership_intents=True)
    new,bundles=order_premises(ev,plan,limit=4,membership_intents=True,module_intents=True)
    assert ev[-1] not in old and new[0]==ev[-1]
    assert bundles[0]['evidenceIds']==[ev[-1]['evidenceId']]
    assert (rows,o)==before


@pytest.mark.parametrize('bad',[TABLE.replace('dataset','benchmark'),TABLE.replace('Method |','Method summary:'),
    TABLE.replace('\n','\nUnrelated interruption\n'),TABLE.replace('Spinach','...'),TABLE+'x'*1300])
def test_horizontal_caption_span_rejects_incomplete_or_nonadjacent_rows(bad):
    assert table_spans(bad,['选择场景的依据'],caption_headers=True)==[]


@pytest.mark.parametrize('version',[8,9])
def test_merged_caption_header_saved_literally_without_membership_or_numeric_approval(version):
    assert table_spans(TABLE,['选择场景的依据'])==[]
    assert table_spans(TABLE,['选择场景的依据'],caption_headers=True)==[TABLE]
    current={'extractionPriorityVersion':version,'adaptiveResearchContractVersion':1,
        'adaptiveExtractionContractVersion':1,'state':{'evidence':[],
        'plan':[{'obligations':[{'obligationId':'o','question':'选择场景的依据','requiredSources':['p']}]}],
        'readResults':[{'sourceId':'s','workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext',
            'location':{'tableColumnMappingUnverified':True},'pages':[{'text':TABLE,'section':'Results'}]}]}}
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    sent=[]
    def invoke(*args):
        sent.append(args[2]);return {'content':'[]'}
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    rows=current['state']['evidence']
    assert len(rows)==(1 if version==9 else 0)
    if rows:
        e=rows[0]
        assert e['quote']==TABLE and e['verification']=={'literal':'passed','semantic':'unchecked'}
        assert e['location']['tableColumnMappingUnverified'] is True and not e.get('tableData')
        assert 'literalDatasetMemberRowsAlreadySaved' in sent[0]
