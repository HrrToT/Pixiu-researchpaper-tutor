from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.request_semantics import normalize_access_requirements,PLAN_GUIDANCE,DRAFT_GUIDANCE
from services.deep_research.request_context import ResearchQuestion
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.verification import make_evidence

EXCERPT='标明实际读到的是全文还是摘要'


def plan():
    return [{'itemId':'item_1','question':'讲解方法','dependencies':[],
        'obligations':[{'obligationId':'access','question':'用户实际阅读的是LightGaussian论文全文还是摘要？',
            'purpose':'answer_requirement','requestExcerpt':EXCERPT,'requiredSources':['paper'],
            'searchQuery':'LightGaussian fulltext abstract','completionCriteria':[
                {'criterionId':'requirement_1','requirement':'根据提供的材料，判断用户实际阅读的是全文还是摘要，并明确标注',
                 'responseType':'identification'}]}]}]


def test_subject_is_projected_from_human_request_before_freezing_without_source_or_id_change():
    original=plan();before=deepcopy(original)
    result,changes=normalize_access_requirements(original,'讲解论文。'+EXCERPT+'。')
    a=result[0]['obligations'][0];b=original[0]['obligations'][0]
    assert a['question']==a['completionCriteria'][0]['requirement']==EXCERPT
    assert a['completionCriteria'][0]['criterionId']=='requirement_1'
    assert a['requiredSources']==b['requiredSources'] and a['searchQuery']==b['searchQuery']
    assert changes[0]['before']['question']==b['question'] and original==before
    assert normalize_access_requirements(result,'讲解论文。'+EXCERPT+'。')==(result,[])


@pytest.mark.parametrize('question',[
    '不用'+EXCERPT,'不要'+EXCERPT,'仅解释论文，不必'+EXCERPT,
    '这只是引文：“'+EXCERPT+'”。请解释模型。',
    ResearchQuestion('模型提出的问题：'+EXCERPT,['只解释方法']),
])
def test_negated_quoted_or_model_authored_access_text_cannot_rewrite_plan(question):
    original=plan()
    assert normalize_access_requirements(original,question)==(original,[])


@pytest.mark.parametrize('change',['mixed','multiple','explanation','supporting','invented_excerpt'])
def test_projection_cannot_erase_scientific_or_unrequested_criteria(change):
    original=plan();o=original[0]['obligations'][0]
    if change=='mixed':o['completionCriteria'][0]['requirement']='标明全文还是摘要并解释方法机制'
    elif change=='multiple':o['completionCriteria'].append({'criterionId':'science','requirement':'解释机制','responseType':'explanation'})
    elif change=='explanation':o['completionCriteria'][0]['responseType']='explanation'
    elif change=='supporting':o['purpose']='supporting_research'
    else:o['requestExcerpt']='明确说明取得的是论文全文还是摘要'
    assert normalize_access_requirements(original,EXCERPT)==(original,[])


@pytest.mark.parametrize('version',[0,1])
def test_plan_graph_normalizes_only_new_runs_and_preserves_raw_response(version):
    raw=plan();record={'question':EXCERPT,'materials':[{'materialId':'paper'}],
        'requestSemanticsContractVersion':version,'state':{'outputKind':'direction_survey'}}
    def update(_,change,**kwargs):
        nonlocal record
        record=change(record);return record
    invoke=Mock(return_value={'content':json.dumps(raw)})
    make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    invoke.assert_called_once();prompt=invoke.call_args.args[2]
    actual=record['state']['plan'][0]['obligations'][0]
    assert (PLAN_GUIDANCE in prompt)==bool(version)
    assert actual['question']==(EXCERPT if version else raw[0]['obligations'][0]['question'])
    assert json.loads(invoke.return_value['content'])==raw


def test_repair_guidance_keeps_original_kind_permissions_and_cache_isolation():
    quote='The method prunes redundant Gaussians.'
    evidence=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=[])
    report={'claims':[{'claimId':'c','kind':'reported','text':'读论文的顺序。','evidenceRefs':[evidence['evidenceId']]}]}
    rejected={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}
    old=_prepare_repair(report,rejected,[evidence],EXCERPT)
    new=_prepare_repair(report,rejected,[evidence],EXCERPT,request_semantics=True)
    assert DRAFT_GUIDANCE in new['prompt'] and new['originals']==old['originals'] and new['allowed']==old['allowed']
    states=[];invoke=Mock(return_value={'content':'[]'})
    repair_rejected(report,rejected,[evidence],EXCERPT,invoke,json.loads,checkpoint=lambda s:states.append(deepcopy(s)))
    from services.deep_research.contracts import DeepResearchError
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):
        repair_rejected(report,rejected,[evidence],EXCERPT,invoke,json.loads,batch_state=states[-1],request_semantics=True)
    invoke.assert_not_called()


@pytest.mark.parametrize('replacement',[None,True,0,1,3,'2'])
def test_semantics_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'test.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':EXCERPT,
            'requestSemanticsContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['requestSemanticsContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'requestSemanticsContractVersion':replacement})
    finally:facade.shutdown()
