from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_rewrite import (rewrite_for_beginner, inference_candidates,
    QUALITATIVE_INFERENCE_REVIEW, _prepare)
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import verify_claims
from test_deep_research_audience_rewrite import fixture

REQUIREMENTS=[{'obligationId':'why','question':'为什么要平衡两个目标','completionCriteria':[]}]


def response(report, **patch):
    return {'content':json.dumps({'claims':[{'claimId':c['claimId'],'text':'据此可理解为，这个目标同时约束数据大小与图像误差。',
        'conditions':{}, **(patch if c['claimId']=='why' else {})} for c in report['claims']]},ensure_ascii=False)}


def test_explicit_why_can_be_source_derived_inference_without_new_permissions_or_approval():
    report,evidence=fixture();before=deepcopy((report,evidence));states=[]
    report['claims'][0]['text']='4DGC由λ1平衡码率和失真。'
    invoke=Mock(return_value=response(report,kind='inference'))
    result=rewrite_for_beginner(report,evidence,'给新手解释为什么',invoke,json.loads,contract_version=4,
        requirement_context=REQUIREMENTS,checkpoint=states.append)
    assert result['claims'][0]['kind']=='inference' and invoke.call_count==1
    assert result['claims'][0]['evidenceRefs']==report['claims'][0]['evidenceRefs']
    assert result['claims'][0]['obligationIds']==report['claims'][0]['obligationIds']
    assert states[-1]['originalReport']==report and states[-1]['classificationChanges']==[
        {'claimId':'why','from':'reported','to':'inference'}]
    assert evidence==before[1] and result['sections']==report['sections']
    assert not verify_claims(result['claims'],evidence)['accepted']
    no_dispatch=Mock(side_effect=AssertionError('No repeat'))
    assert rewrite_for_beginner(report,evidence,'给新手解释为什么',no_dispatch,json.loads,contract_version=4,
        requirement_context=REQUIREMENTS,saved_state=states[-1])==result
    no_dispatch.assert_not_called()


@pytest.mark.parametrize('text',['300 FPS','999个高斯','三组实验','十五倍压缩','百分之十五','λ1控制参数'])
def test_quantities_cannot_be_laundered_by_changing_reported_to_inference(text):
    report,evidence=fixture();invoke=Mock(return_value=response(report,kind='inference',text=text))
    result=rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=4,
        requirement_context=REQUIREMENTS)
    assert result==report and invoke.call_count==1


def test_original_measured_claim_is_not_eligible_even_if_editor_drops_its_number():
    report,evidence=fixture();report['claims'][0]['text']='压缩15倍。'
    assert inference_candidates(report,REQUIREMENTS)==set()
    result=rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:response(report,kind='inference'),
        json.loads,contract_version=4,requirement_context=REQUIREMENTS)
    assert result==report


@pytest.mark.parametrize('patch',[{'kind':'reported'},{'kind':'hypothesis'},
    {'kind':'inference','evidenceRefs':['foreign']},{'kind':'inference','claimId':'how'}])
def test_editor_cannot_choose_arbitrary_kind_citations_or_target(patch):
    report,evidence=fixture()
    result=rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:response(report,**patch),json.loads,
        contract_version=4,requirement_context=REQUIREMENTS)
    assert result==report


def test_whole_question_why_does_not_authorize_an_unrelated_how_target():
    report,evidence=fixture();report['claims'][0]['obligationIds']=['how']
    assert inference_candidates(report,REQUIREMENTS)==set()


def test_source_first_generation_does_not_receive_old_unverified_reasoning():
    report,evidence=fixture();report['claims'][0]['text']='OLD_UNVERIFIED_CAUSAL_GUARANTEE'
    request,error=_prepare(report,evidence,'给新手解释',contract_version=4,requirement_context=REQUIREMENTS)
    assert error is None and 'OLD_UNVERIFIED_CAUSAL_GUARANTEE' not in request['prompt']
    assert evidence[0]['quote'] in request['prompt'] and '"why"' in request['prompt']
    assert request['outputTokens']==3072 and len(request['prompt'].encode())<=24000


def test_inference_still_receives_an_independent_failable_semantic_judgment():
    report,evidence=fixture();claim=report['claims'][0];claim['kind']='inference'
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'why','status':'failed','reason':'Invented consequence'}])})
    result=BudgetedSemanticChecker(invoke,'r',qualitative_inference=True)([claim],evidence)
    assert result[0]['status']=='failed' and QUALITATIVE_INFERENCE_REVIEW in invoke.call_args.kwargs['prompt']
    old=Mock(return_value={'content':json.dumps([{'claimId':'why','status':'failed','reason':'No support'}])})
    BudgetedSemanticChecker(old,'r')([claim],evidence)
    assert QUALITATIVE_INFERENCE_REVIEW not in old.call_args.kwargs['prompt']


def test_pending_source_first3_cannot_be_retargeted_to_classification4():
    report,evidence=fixture();states=[]
    def unknown(*_):raise OSError('unknown')
    with pytest.raises(OSError):
        rewrite_for_beginner(report,evidence,'给新手解释',unknown,json.loads,contract_version=3,checkpoint=states.append)
    invoke=Mock()
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=4,
            requirement_context=REQUIREMENTS,saved_state=states[-1])
    invoke.assert_not_called()
