from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.access_request_projection import project
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from services.deep_research.request_context import ResearchQuestion

EXCERPT='标明实际读到的是全文还是摘要。'


def plan(description='明确说明所依据的材料是全文还是摘要（基于提供的PDF文件内容判断）。'):
    return [{'itemId':'i','question':'读论文','dependencies':[],'obligations':[
        {'obligationId':'a','question':'实际读到的是Paper-X的全文还是摘要？','purpose':'answer_requirement',
         'requestExcerpt':EXCERPT,'requiredSources':['p'],'searchQuery':'paper',
         'completionCriteria':[{'criterionId':'access','requirement':description,'responseType':'identification'}]}]}]


@pytest.mark.parametrize('description',[
    '明确说明所依据的材料是全文还是摘要（基于提供的PDF文件内容判断）。',
    '说明全文还是摘要（输入为PDF-v12，路径由系统提供）。',
    '说明全文还是摘要，并给出判断依据。',
    '说明全文还是摘要，附注：按已获取文档判断。',
])
def test_human_access_intent_does_not_depend_on_generated_description_lexicon(description):
    original=plan(description);before=deepcopy(original)
    result,changes=project(original,'说明压缩方法。'+EXCERPT)
    a=result[0]['obligations'][0];b=original[0]['obligations'][0]
    assert a['question']==a['completionCriteria'][0]['requirement']==EXCERPT
    assert a['requiredSources']==b['requiredSources'] and a['completionCriteria'][0]['criterionId']=='access'
    assert changes[0]['before']['completionCriteria'][0]['requirement']==description and original==before


@pytest.mark.parametrize('description',[
    '说明全文还是摘要并比较实验结果','说明全文还是摘要并给出30dB指标','解释SH算法机制',
])
def test_scientific_or_mixed_criterion_is_not_projected(description):
    original=plan(description)
    assert project(original,EXCERPT)==(original,[])


@pytest.mark.parametrize('question',[
    '不用'+EXCERPT,'引文：“'+EXCERPT+'”',
    ResearchQuestion('模型建议：'+EXCERPT,['只解释机制']),
    EXCERPT+'并给出判断依据',EXCERPT.rstrip('。')+'并说明依据',
])
def test_unrequested_negated_quoted_or_explicit_additional_human_requirement_stays_intact(question):
    original=plan('说明全文还是摘要，并给出判断依据，并说明依据')
    assert project(original,question)==(original,[])


@pytest.mark.parametrize('version',[0,1])
def test_projection_runs_in_plan_graph_only_for_new_contract(version):
    raw=plan();record={'question':EXCERPT,'materials':[{'materialId':'p'}],
        'accessRequestProjectionContractVersion':version,'state':{'outputKind':'direction_survey'}}
    def update(_,change,**kwargs):
        nonlocal record
        record=change(record);return record
    invoke=Mock(return_value={'content':json.dumps(raw)})
    make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert record['state']['plan'][0]['obligations'][0]['question']==(EXCERPT if version else raw[0]['obligations'][0]['question'])
    assert bool(record['state'].get('planAccessRequestProjection'))==bool(version)
    invoke.assert_called_once()


@pytest.mark.parametrize('replacement',[None,True,0,3,'1'])
def test_projection_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':EXCERPT,'deferStart':True,
            'accessRequestProjectionContractVersion':replacement},start_async=False)
        assert run['accessRequestProjectionContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'accessRequestProjectionContractVersion':replacement})
    finally:facade.shutdown()


def test_citation_access_contract_keeps_original_excerpt_and_legacy_wire():
    excerpt='标明本次实际引用的是全文片段还是摘要'
    raw=plan('说明所引用内容来自论文全文的哪个部分。')
    obligation=raw[0]['obligations'][0]
    obligation['requestExcerpt']=excerpt
    obligation['question']='本次实际引用的是全文片段还是摘要？'
    before=deepcopy(raw)
    assert project(raw,excerpt)==(raw,[])
    result,audit=project(raw,excerpt,citation_access=True)
    output=result[0]['obligations'][0]
    assert output['question']==output['completionCriteria'][0]['requirement']==excerpt.replace('引用','依据')
    assert output['requestExcerpt']==excerpt and raw==before
    assert audit[0]['requestExcerpt']==excerpt
    from services.deep_research.access_disclosure import access_requirements
    assert access_requirements(result)=={'a':{'overall':True,'criteria':{'access'}}}


@pytest.mark.parametrize('extra',['并说明具体位置','并解释实验结果','并比较机制','并给出判断依据'])
def test_citation_access_cannot_erase_actual_additional_requests(extra):
    excerpt='标明本次实际引用的是全文片段还是摘要'+extra
    raw=plan(excerpt);raw[0]['obligations'][0]['requestExcerpt']=excerpt
    assert project(raw,excerpt,citation_access=True)==(raw,[])
