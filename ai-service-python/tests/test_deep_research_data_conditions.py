from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.data_conditions import requested_conditions,condition_score
from services.deep_research.criterion_sources import acquisition_conditions,include_indexed_criteria,include_pdf_criteria
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.synthesis_evidence import order_premises
from services.deep_research.extraction import _extraction_prompt
from test_deep_research_method_details import passage
from test_deep_research_local_sources import fixture as local_fixture

QUESTION='只选择一个有新出现内容的场景，固定相同TMC结果，比较跳过或执行第2阶段。'
TEXT='We evaluate the ablation on the ExampleAlpha scene. The baseline without the second stage fails to capture emerging objects.'


def obligation():
    return {'obligationId':'o','question':QUESTION,'searchQuery':'experiment data selection',
        'requiredSources':['p'],'completionCriteria':[{'criterionId':'data','requirement':'核对数据集成员',
                                                       'responseType':'explanation'}]}


@pytest.mark.parametrize('q,expected',[(QUESTION,['emergence']),('使用存在遮挡的场景',['occlusion']),
    ('Choose a newly appearing object sequence',['emergence']),('Compare dataset names',[]),
    ('Choose an occluded sequence',['occlusion'])])
def test_explicit_conditions_only(q,expected):
    assert requested_conditions(q)==expected


@pytest.mark.parametrize('body,section',[
    ('The ExampleAlpha scene belongs to the DatasetA dataset.','Datasets'),
    ('Our method models emerging objects in dynamic scenes.','Method'),
    ('Paper: ExampleAlpha emerging objects\nContent: The experiment has results.','Evaluation'),
    (TEXT,'Related Work'),(TEXT,'References')])
def test_generic_membership_motivation_wrappers_and_related_work_are_not_prerequisites(body,section):
    assert condition_score(body,section,'emergence')==0


def test_only_matching_human_and_source_bound_obligation_supply_conditions():
    o=obligation();r={'question':QUESTION,'state':{'plan':[{'obligations':[o]}]}};before=deepcopy(r)
    assert acquisition_conditions(r,o['searchQuery'],'p')==['emergence']
    assert acquisition_conditions(r,o['searchQuery'],'foreign')==[]
    assert acquisition_conditions(r,'unrelated','p')==[]
    assert acquisition_conditions({**r,'question':'比较数据集'},o['searchQuery'],'p')==[]
    assert r==before


def test_existing_slots_cover_both_module_and_condition_without_mutating_source():
    selected=[passage(i,'Generic dataset membership overview.') for i in range(5)]
    module=passage(21,'TMC encodes input and predicts translation and rotation outputs.')
    detail=passage(38,TEXT,section='Evaluation');before=deepcopy((selected,module,detail))
    found=include_indexed_criteria(selected,[module,detail],[],'p',5,modules=['TMC'],conditions=['emergence'])
    assert len(found)==5 and found[0]==selected[0]
    assert {module['sourceId'],detail['sourceId']}<={r['sourceId'] for r in found}
    assert all(r['text']==next(s['text'] for s in [*selected,module,detail] if s['sourceId']==r['sourceId']) for r in found)
    assert include_indexed_criteria(selected,[detail],[],'p',5)==selected
    assert (selected,module,detail)==before


@pytest.mark.parametrize('mutation',['owner','version','duplicate'])
def test_condition_never_expands_to_wrong_or_ambiguous_index_identity(mutation):
    selected=[passage(i,'Generic overview.') for i in range(5)]
    detail=passage(38,TEXT,owner='q' if mutation=='owner' else 'p',
                   version='b'*16 if mutation=='version' else 'a'*16,section='Evaluation')
    candidates=[detail,deepcopy(detail)] if mutation=='duplicate' else [detail]
    assert include_indexed_criteria(selected,candidates,[],'p',5,conditions=['emergence'])==selected


def test_pdf_hash_and_existing_slots_stay_required():
    top={'sourceId':'top','pdfId':'p','contentHash':'h','accessLevel':'fulltext','text':'Overview.'}
    good={**top,'sourceId':'good','text':TEXT,'location':{'section':'Evaluation'}}
    wrong={**good,'sourceId':'bad','contentHash':'other'}
    assert include_pdf_criteria([top],[wrong,good],[],'p','h',2,conditions=['emergence'])==[top,good]
    assert include_pdf_criteria([top],[wrong],[],'p','h',2,conditions=['emergence'])==[top]
    assert include_pdf_criteria([top],[good],[],'p','h',1,conditions=['emergence'])==[top]


def test_reading_and_premise_cover_named_condition_not_just_member_list():
    from test_deep_research_reading_priority import source
    from test_deep_research_synthesis_premises import evidence
    o=obligation();rows=[source('p',i,'Datasets','The named scene is in the DatasetA dataset.',('o',)) for i in range(15)]
    detail=source('p',38,'Evaluation',TEXT,('o',));rows.append(detail)
    old=select_read_sources(rows,{'o':o},12,priority_version=9)
    new=select_read_sources(rows,{'o':o},12,priority_version=10)
    assert detail not in old and detail in new and len(new)<=12
    ev=[evidence(str(i),s['text']) for i,s in enumerate(rows)];before=deepcopy((ev,o))
    old,_=order_premises(ev,[{'obligations':[o]}],limit=4,module_intents=True,membership_intents=True)
    new,_=order_premises(ev,[{'obligations':[o]}],limit=4,module_intents=True,membership_intents=True,condition_intents=True)
    assert ev[-1] not in old and ev[-1] in new and len(new)<=4
    assert (ev,o)==before
    assert 'named scene/sample AND its observed applicability condition' in _extraction_prompt([],10)
    assert 'named scene/sample AND its observed applicability condition' not in _extraction_prompt([],9)


@pytest.mark.parametrize('version',[7,8])
def test_production_acquisition_keeps_original_query_and_cache_budget(monkeypatch,version):
    from services.tools import retrieval_tools
    local,get,parse,_=local_fixture(monkeypatch)
    local.repo.require_run.return_value.update(question=QUESTION,sourcePrecisionContractVersion=version,
        state={'plan':[{'obligations':[obligation()]}]})
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    def doc(i,text,owner='p'):
        return {'text':text,'metadata':{'id':owner,'index_version':'a'*16,'chunk_index':i,
                                      'section_title':'Evaluation','page':8}}
    rag=Mock();rag.normalize_id.side_effect=lambda x:x
    rag.get_documents_by_metadata.return_value=[doc(38,TEXT),doc(99,TEXT,'q')]
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=[doc(i,'Generic overview.') for i in range(5)])
    monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    found=local(obligation()['searchQuery'],'p',limit=5)
    assert (38 in {r['chunkIndex'] for r in found})==(version==8)
    assert len(found)<=5 and all(r['pdfId']=='p' for r in found)
    retrieve.assert_called_once();rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    assert get.call_count==parse.call_count==1
