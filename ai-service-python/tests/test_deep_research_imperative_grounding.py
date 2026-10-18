from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.coverage import validate_plan
from services.deep_research.evidence_requirements import normalize_generated_requirements,imperative_grounded
from services.deep_research.graph import make_plan_node
from services.deep_research.request_context import ResearchQuestion


def plan(excerpt):
    return [{'itemId':'i','question':'List every metric value','obligations':[
        {'obligationId':'o','question':'List every metric value','requestExcerpt':excerpt,
         'requiredSources':['paper'],'completionCriteria':[
             {'criterionId':'generated','requirement':'List all measurements and numbers','responseType':'identification'}]}]}]


@pytest.mark.parametrize('human,expected',[
    ('只依据本文，核查压缩后质量接近基线这一说法。',['核查压缩后质量接近基线这一说法']),
    ('区分作者报告的结果、成立条件和未验证范围。',['区分作者报告的结果、成立条件和未验证范围']),
    ('比较存储、速度和画质，解释质量下降的原因。',['比较存储、速度和画质','解释质量下降的原因']),
    ('Compare storage, speed, and quality, and explain the tradeoff.',['Compare storage, speed, and quality','and explain the tradeoff.']),
    ('核查“模型在所有条件都无损，为什么”这一主张，指出证据边界。',['核查“模型在所有条件都无损，为什么”这一主张','指出证据边界']),
    ('设计实验（固定相机，分辨率），说明适用范围。',['设计实验（固定相机，分辨率）','说明适用范围']),
])
def test_literal_actions_keep_requested_judgement_and_object_lists(human,expected):
    original=plan(human);before=deepcopy(original)
    result,changes=normalize_generated_requirements(original,human,literal_questions=True,literal_imperatives=True)
    o=result[0]['obligations'][0]
    assert [c['requirement'] for c in o['completionCriteria']]==expected
    assert o['question']==human and result[0]['question']==human and changes and original==before
    assert 'all measurements' not in json.dumps(o)


@pytest.mark.parametrize('human,kind',[
    ('核查是否所有指标都无损','explanation'),
    ('判断是否能直接比较','explanation'),
    ('区分作者报告的结果、成立条件和未验证范围','limitation'),
    ('设计一个四组对照实验','procedure'),
    ('给出可执行的对照方案','procedure'),
    ('What changes are predicted','identification'),
    ('为什么要固定相机','explanation'),
])
def test_response_type_preserves_judgement_procedure_and_limits(human,kind):
    result,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True)
    assert result[0]['obligations'][0]['completionCriteria'][0]['responseType']==kind


@pytest.mark.parametrize('human',['只写两点，300字以内。','不要解释无关的理论。','作者解释了测量设置。','“解释这个现象”是一个例子。','“为什么不损失质量”只是引用的标题。'])
def test_format_limits_negative_commands_and_quoted_examples_are_not_new_deliverables(human):
    original=plan(human)
    result,changes=normalize_generated_requirements(original,human,literal_questions=True,literal_imperatives=True)
    assert result==original and not changes


def test_saved_parent_artifact_cannot_supply_command_or_literal_excerpt():
    excerpt='核查全部指标是否无损'
    original=plan(excerpt)
    q=ResearchQuestion('UNVERIFIED PARENT: '+excerpt,['只解释第二点的原因'])
    result,changes=normalize_generated_requirements(original,q,literal_questions=True,literal_imperatives=True)
    assert result==original and not changes


@pytest.mark.parametrize('version',[None,True,1,2])
def test_actual_initial_plan_node_versions_the_policy_without_extra_model_calls(version):
    human='核查压缩后画质接近基线这一说法。区分作者报告的结果、成立条件和未验证范围。'
    original=plan(human)
    record={'question':human,'requestGroundingContractVersion':version,'evidenceCoverageContractVersion':3,
            'planCompletionContractVersion':1,'materials':[{'materialId':'paper'}],'state':{'outputKind':'claim_verification'}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(original)})
    assert make_plan_node(invoke,update,validate_plan)({'run_id':'r'})['plan_ids']==['i']
    invoke.assert_called_once()
    criteria=record['state']['plan'][0]['obligations'][0]['completionCriteria']
    if type(version) is int and version==2:
        assert [c['responseType'] for c in criteria]==['explanation','limitation']
        assert criteria[0]['requirement']=='核查压缩后画质接近基线这一说法'
    else: assert criteria==original[0]['obligations'][0]['completionCriteria']


@pytest.mark.parametrize('version',[None,True,False,0,1,'2',3])
def test_imperative_policy_strict_version(version):
    assert not imperative_grounded({'requestGroundingContractVersion':version})
    assert imperative_grounded({'requestGroundingContractVersion':2})
