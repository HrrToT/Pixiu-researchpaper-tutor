from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.method_intent import query_intent,query_intents
from services.deep_research.criterion_sources import acquisition_questions,include_indexed_criteria,include_pdf_criteria
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.literal_equations import method_equations
from services.deep_research.verification import make_evidence
from test_deep_research_method_details import passage
from test_deep_research_local_sources import fixture as local_fixture


COMPOUND='它们使用什么输入，怎样表示时间变化，训练是逐帧在线还是整体离线'


def obligation(paper='p'):
    return {'obligationId':'o','question':COMPOUND,'requiredSources':[paper],
        'searchQuery':'Paper input time representation training',
        'completionCriteria':[{'criterionId':'input','requirement':'它们使用什么输入','responseType':'identification'},
                              {'criterionId':'rest','requirement':'怎样表示时间变化，训练是逐帧在线还是整体离线','responseType':'explanation'}]}


def test_compound_intents_are_independent_without_changing_legacy_first_intent():
    assert query_intent(COMPOUND,operational=True)=='input'
    assert query_intents(COMPOUND)==['input','temporal','training']
    assert query_intents('annealing smoothing training mechanism')==['operation']
    assert query_intents('指出为何不能凭各自主表FPS给出同条件速度排名')==['measurement:fps','comparison_result:fps']
    assert query_intents('比较PSNR与SSIM')==['measurement:psnr','measurement:ssim']
    assert query_intents('unrelated FPSCounter identifier')==[]


def test_main_table_request_retains_both_measurement_context_and_a_comparison_not_just_a_microbenchmark():
    from services.deep_research.method_intent import operation_score
    main='Table 8. Quantitative comparison on a dataset. Method | PSNR | FPS. Ours | 30 | 100.'
    micro='Table 1. Rendering profiling. Query overhead | FPS. Without cache | 100.'
    assert operation_score(main,'Table 8. Quantitative comparison','comparison_result:fps',operational=True)>0
    assert operation_score(micro,'Table 1. Rendering profiling','comparison_result:fps',operational=True)==0
    # New ranking never changes the old single-intent/operation policies.
    assert operation_score(main,'Table 8. Quantitative comparison','comparison_result:fps')==0


def test_only_matching_source_permitted_frozen_criteria_supply_hints():
    o=obligation();record={'state':{'plan':[{'obligations':[o]}]}};before=deepcopy(record)
    assert acquisition_questions(record,o['searchQuery'],'p')==[c['requirement'] for c in o['completionCriteria']]
    assert acquisition_questions(record,COMPOUND+'；缺口补查','p')
    assert acquisition_questions(record,o['searchQuery'],'foreign')==[]
    assert acquisition_questions(record,'unrelated query','p')==[]
    assert record==before


def test_each_owned_aspect_gets_an_existing_slot_and_never_replaces_previous_aspects():
    selected=[passage(i,'General overview of input time representation training.',section='Introduction') for i in range(5)]
    details=[passage(15,'The input to our method is monocular images with calibrated camera poses.'),
             passage(16,'Our canonical time field outputs position, rotation and scale offsets.'),
             passage(30,'We initially train the model. Subsequently we jointly train both components for fixed iterations.',section='Implementation')]
    candidates=[*details,passage(40,details[-1]['text'],owner='foreign'),
                passage(50,details[-1]['text'],version='b'*16)]
    before=deepcopy((selected,candidates));questions=[c['requirement'] for c in obligation()['completionCriteria']]
    found=include_indexed_criteria(selected,candidates,questions,'p',5)
    assert found[0]==selected[0] and len(found)==5
    assert {r['metadata']['chunk_index'] for r in found}>={15,16,30}
    assert all(r in selected or r['sourceId'] in {d['sourceId'] for d in details} for r in found)
    assert all(r['text']==next(x['text'] for x in [*selected,*candidates] if x['sourceId']==r['sourceId']) for r in found)
    assert (selected,candidates)==before
    # A full protected envelope cannot expand to fit another passage.
    tiny=include_indexed_criteria(selected[:1],candidates,questions,'p',1)
    assert tiny==selected[:1]


@pytest.mark.parametrize('precision',[5,6])
def test_production_local_retriever_uses_exact_same_query_and_index_cache_for_all_aspects(monkeypatch,precision):
    from services.tools import retrieval_tools
    local,get,parse,_validate=local_fixture(monkeypatch)
    record=local.repo.require_run.return_value
    record.update(sourcePrecisionContractVersion=precision,state={'plan':[{'obligations':[obligation()]}]})
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def doc(index,text,section='Method',owner='p'):
        return {'text':text,'metadata':{'id':owner,'index_version':'a'*16,
            'chunk_index':index,'section_title':section,'page':4}}
    indexed=[doc(i,'General input time representation training overview.','Introduction') for i in range(5)]
    corpus=[doc(15,'The input to our method is monocular images with calibrated camera poses.'),
        doc(16,'Our canonical time field outputs position, rotation and scale offsets.'),
        doc(30,'We initially train the model. Subsequently we jointly train both components for fixed iterations.','Implementation'),
        doc(99,'Our foreign method jointly trains offline in two stages.','Implementation','foreign')]
    rag=Mock();rag.normalize_id.side_effect=lambda value:value;rag.get_documents_by_metadata.return_value=corpus
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=indexed);monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    query=obligation()['searchQuery'];found=local(query,'p',limit=5)
    chunks={r['chunkIndex'] for r in found}
    assert 0<len(found)<=5 and all(r['pdfId']=='p' for r in found)
    assert ({15,16,30}<=chunks)==(precision==6)
    retrieve.assert_called_once_with(query,top_k=8,filter_metadata={'id':'p'},allow_query_rewrite=False)
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    assert get.call_count==parse.call_count==1  # Existing optional identity read; no extra model/search.


def test_criterion_reading_and_extraction_cover_both_papers_within_six_slots():
    obs={};sources=[]
    for paper in ('a','b'):
        o=obligation(paper);o['obligationId']=paper;obs[paper]=o
        for i,section,text in [(0,'Method','The input to our method is monocular images with camera poses.'),
            (1,'Method','Our canonical time field outputs position, rotation and scale offsets.'),
            (2,'Implementation','We initially train the model. Subsequently we jointly train both components for fixed iterations.'),
            (99,'Method','The input to our method is monocular images with camera poses, without further method detail.')]:
            sources.append({'sourceId':f'{paper}-v'+('a'*16)+f'-chunk-{i}',
                'workId':paper,'versionId':'v','contentHash':str(i),'obligationIds':[paper],
                'text':text,'location':{'section':section}})
    before=deepcopy((sources,obs));selected=select_read_sources(sources,obs,6,priority_version=7)
    pending=[(s,s['location'],s['text']) for s in sources]
    ranked=prioritize_extraction_passages(pending,obs,7)
    assert len(selected)==6 and len({s['sourceId'] for s in selected})==6
    expected={s['sourceId'] for s in sources if s['location']['section']=='Implementation'
              or not s['sourceId'].endswith('-99')}
    assert {row[0]['sourceId'] for row in ranked[:6]}==expected
    assert {s['sourceId'] for s in selected}==expected
    assert {s['sourceId'] for s in select_read_sources(sources,obs,6,priority_version=6)}!=expected
    assert (sources,obs)==before


def test_pdf_fallback_keeps_hash_ownership_and_the_original_top_hit():
    rows=[{'sourceId':str(i),'pdfId':'p','contentHash':'h','accessLevel':'fulltext',
           'text':text,'location':{}} for i,text in enumerate([
        'General paper input time representation training overview.',
        'The input to our method is monocular images with camera poses.',
        'Our canonical time field outputs position and rotation offsets.',
        'We initially train the model. Subsequently we jointly train both components for fixed iterations.'])]
    foreign={**rows[-1],'sourceId':'foreign','pdfId':'q'}
    changed={**rows[-1],'sourceId':'changed','contentHash':'changed'}
    found=include_pdf_criteria(rows[:1],[*rows,foreign,changed],[COMPOUND],'p','h',4)
    assert found==rows and len(found)==4


EQUATION='Equation: d = F(g(x), g(t) + X(i)), X(i) = N(0, 1) * beta * dt * (1 - i/tau).'
TEXT='We add noise to the encoded time. The noise decays during training. Our method improves image quality.\n'+EQUATION


def extract_record(version=7,access='fulltext'):
    return {'runId':'r','extractionPriorityVersion':version,'adaptiveResearchContractVersion':1,
        'adaptiveExtractionContractVersion':1,'state':{'evidence':[],
        'plan':[{'obligations':[{'obligationId':'o','question':'解释退火平滑的实现机制','requiredSources':['p']}]}],
        'readResults':[{'sourceId':'s','workId':'p','versionId':'v','contentHash':'h','accessLevel':access,
            'title':'Paper','pages':[{'page':4,'section':'Technique','text':TEXT}]}]}}


@pytest.mark.parametrize('version',[6,7])
def test_equation_uses_one_of_three_slots_and_never_becomes_semantically_approved(version):
    record=extract_record(version);sent=[]
    def update(_id,change,**kw):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    def invoke(_id,node,prompt,_options):
        sent.append(prompt)
        return {'content':json.dumps([{'sourceId':'s','quote':q,'obligationIds':['o']}
            for q in ['We add noise to the encoded time.','The noise decays during training.',
                      'Our method improves image quality.']])}
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    evidence=record['state']['evidence'];assert len(evidence)==3 and len(sent)==1
    equations=[e for e in evidence if e.get('extractionKind')=='literal_method_equation']
    assert bool(equations)==(version==7)
    if version==7:
        assert equations[0]['quote']==EQUATION and equations[0]['sourceWorkId']=='p'
        assert equations[0]['verification']=={'literal':'passed','semantic':'unchecked'}
        assert 'at most TWO' in sent[0] and 'literalMethodEquationsAlreadySaved' in sent[0]
        assert 'Our method improves image quality.' not in [e['quote'] for e in evidence]


@pytest.mark.parametrize('access',['abstract','user_note'])
def test_abstract_or_note_never_gets_program_method_equation(access):
    record=extract_record(access=access)
    def update(_id,change,**kw):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    make_batched_extract_node(lambda *_:{'content':'[]'},make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert record['state']['evidence']==[]


@pytest.mark.parametrize('response',[{'content':'bad JSON'}, {'content':'[]','finishReason':'length'}])
def test_invalid_model_extraction_does_not_invent_received_status_for_the_literal_equation(response):
    record=extract_record()
    def update(_id,change,**kw):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    make_batched_extract_node(lambda *_:response,make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert len(record['state']['evidence'])==1
    assert set(record['state']['reviewedExtractionPassages'].values())==({'invalid'} if response['content']=='bad JSON' else {'truncated'})


def test_unknown_send_preserves_literal_data_but_no_model_review_receipt():
    record=extract_record()
    def update(_id,change,**kw):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    with pytest.raises(OSError):
        make_batched_extract_node(Mock(side_effect=OSError('unknown')),make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert len(record['state']['evidence'])==1 and not record['state'].get('reviewedExtractionPassages')


@pytest.mark.parametrize('text',['Equation: x =','Equation: x = f(t','Equation: x = t ...','Equation: '+('x'*1200)+' = t'])
def test_incomplete_or_oversize_equation_is_not_clipped_into_evidence(text):
    assert method_equations(text,['解释方法操作'])==[]
    assert method_equations(TEXT,['report FPS'])==[]
