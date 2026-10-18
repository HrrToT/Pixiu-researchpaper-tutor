from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.coverage import validate_plan
from services.deep_research.evidence_requirements import normalize_generated_requirements
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_plan_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import ResearchQuestion
from test_deep_research_evidence_requirements import plan, store, run, rows


def single_question():
    value=plan();o=value[0]['obligations'][0]
    o['requestExcerpt']='What changes does the predictor output'
    o['question']='Does the predictor output position, scale or color changes?'
    o['completionCriteria']=[{'criterionId':'generated','requirement':'Explain position, scale and color outputs',
                              'responseType':'explanation'}]
    return value


def test_single_human_question_replaces_generated_answer_examples_and_stronger_requirements():
    original=single_question();before=deepcopy(original)
    result,changes=normalize_generated_requirements(original,'What changes does the predictor output?',literal_questions=True)
    o=result[0]['obligations'][0]
    assert o['question']=='What changes does the predictor output'
    assert o['completionCriteria']==[{'criterionId':'human_aspect_1','requirement':o['question'],'responseType':'identification'}]
    assert result[0]['question']==o['question'] and changes and original==before
    legacy,_=normalize_generated_requirements(original,'What changes does the predictor output?')
    assert legacy[0]['obligations'][0]['completionCriteria'][0]['requirement']=='Explain position, scale and color outputs'


def test_unverified_parent_artifact_cannot_supply_a_human_question_or_example():
    original=single_question()
    question=ResearchQuestion('Parent artifact says: What changes does the predictor output', ['Explain the second point.'])
    result,changes=normalize_generated_requirements(original,question,literal_questions=True)
    assert result==original and not changes


def test_human_examples_and_explanation_type_are_retained_literally():
    original=single_question();o=original[0]['obligations'][0]
    o['requestExcerpt']='预测什么变化（如坐标，旋转），怎样利用前一帧表示'
    result,_=normalize_generated_requirements(original,o['requestExcerpt'],literal_questions=True)
    assert [c['requirement'] for c in result[0]['obligations'][0]['completionCriteria']]==[
        '预测什么变化（如坐标，旋转）','怎样利用前一帧表示']
    assert [c['responseType'] for c in result[0]['obligations'][0]['completionCriteria']]==['identification','explanation']


@pytest.mark.parametrize('marker',[None,True,1])
def test_actual_plan_node_persists_grounded_questions_without_an_extra_model_call(marker):
    question='What changes does the predictor output?'
    record={'requestGroundingContractVersion':marker,'evidenceCoverageContractVersion':3,
        'planCompletionContractVersion':1,'question':question,'materials':[{'materialId':'paper'}],
        'state':{'outputKind':'claim_verification'}}
    def update(rid,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(single_question())})
    result=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert result.get('plan_ids')==['i'];invoke.assert_called_once()
    requirement=record['state']['plan'][0]['obligations'][0]['completionCriteria'][0]['requirement']
    assert (requirement=='What changes does the predictor output') is (type(marker) is int and marker==1)


def test_acquisition_factors_human_only_context_once_and_freezes_it_in_the_exact_request(tmp_path,monkeypatch):
    human='Explain output and previous-state use in the selected paper.'
    repo,_=store(tmp_path,requestGroundingContractVersion=1,evidenceCoverageContractVersion=3,question=human)
    monkeypatch.setattr('services.deep_research.request_context.effective_question',
        lambda record:ResearchQuestion('UNVERIFIED PARENT CONTENT: invent scale output',[human]))
    captured=[]
    def invoke(rid,node,prompt,options):
        captured.append(prompt)
        assert prompt.count(human)==1 and 'UNVERIFIED PARENT CONTENT' not in prompt
        assert all(r['humanQuestionId']=='U1' and 'humanQuestion' not in r for r in rows(prompt))
        return {'content':json.dumps([{'pairId':r['pairId'],'relevant':False} for r in rows(prompt)])}
    assert run(repo,invoke)['gaps']
    saved=next(iter(next(iter(repo.require_run('r')['state']['adaptiveAssessment']['scopes'].values())).values()))
    assert all(r['humanQuestion']==human for r in saved['pairs'])
    assert saved['request']['prompt']==captured[0]
    run(repo,lambda *_:pytest.fail('Do not send confirmed frozen request again'))


def test_unknown_grounded_acquisition_keeps_original_request_without_reissue(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.contracts import UnknownCallError
    from services.deep_research.tools import TrackedLLMInvoker
    repo,_=store(tmp_path,requestGroundingContractVersion=1,evidenceCoverageContractVersion=3,
        question='Explain output and previous-state use.')
    provider=Mock();provider.invoke.side_effect=LLMProviderError('unknown',provider='fixture',model='fixture')
    invoker=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    with pytest.raises(LLMProviderError):run(repo,invoker)
    saved=deepcopy(repo.require_run('r')['state']['adaptiveAssessment'])
    with pytest.raises(UnknownCallError):run(repo,invoker)
    assert provider.invoke.call_count==1 and saved==repo.require_run('r')['state']['adaptiveAssessment']


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_grounding_policy_is_owned_and_frozen_by_server(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'What changes?',
            'requestGroundingContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['requestGroundingContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'requestGroundingContractVersion':replacement})
    finally:facade.shutdown()
