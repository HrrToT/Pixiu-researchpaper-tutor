from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.completion_criteria import completion_criteria_gaps,validate_completion_criteria
from services.deep_research.coverage import validate_plan
from services.deep_research.evidence_requirements import normalize_generated_requirements
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_plan_node,make_verify_node
from services.deep_research.request_dimensions import split_dimensions,enabled,FINAL_DIMENSION_POLICY
from services.deep_research.request_context import ResearchQuestion
from test_deep_research_imperative_grounding import plan


@pytest.mark.parametrize('human,labels',[
    ('区分作者报告的结果、成立条件和未验证范围',['作者报告的结果','成立条件','未验证范围']),
    ('请区分结果、条件和范围',['结果','条件','范围']),
    ('Distinguish reported results, applicable conditions, and unverified scope',['reported results','applicable conditions','unverified scope']),
    ('区分原文证据、当前推断以及建议的适用范围',['原文证据','当前推断','建议的适用范围']),
])
def test_requested_answer_dimensions_are_exact_independent_literal_slices(human,labels):
    original=plan(human);before=deepcopy(original)
    result,_=normalize_generated_requirements(original,human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    criteria=result[0]['obligations'][0]['completionCriteria']
    assert [c['requirement'] for c in criteria]==labels
    assert all(c['requirement'] in human for c in criteria)
    assert result[0]['question']==human and original==before
    validate_completion_criteria(result,required=True)


@pytest.mark.parametrize('human',[
    '区分LightGaussian和3DGS','区分PSNR和SSIM','比较存储、速度和画质',
    '区分“结果、条件和范围”这个例子与实际问题','说明结果、条件和范围',
])
def test_scientific_entity_contrasts_and_quoted_examples_are_not_new_dimension_criteria(human):
    assert split_dimensions(human) is None


def test_old_contract_two_keeps_compound_criterion_and_new_policy_does_not_erase_other_requests():
    human='核查压缩后质量这一说法；区分作者报告的结果、成立条件和未验证范围'
    original=plan(human)
    old,_=normalize_generated_requirements(original,human,literal_questions=True,literal_imperatives=True)
    new,_=normalize_generated_requirements(original,human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    assert len(old[0]['obligations'][0]['completionCriteria'])==2
    criteria=new[0]['obligations'][0]['completionCriteria']
    assert len(criteria)==4 and [c['responseType'] for c in criteria]==['explanation','explanation','limitation','limitation']
    assert criteria[0]['requirement']=='核查压缩后质量这一说法'


def test_maximum_four_preserves_whole_compound_instead_of_silently_losing_extra_facets():
    human='核查质量这一说法；解释下降原因；区分作者报告的结果、成立条件和未验证范围'
    old,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True)
    new,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    assert new==old and len(new[0]['obligations'][0]['completionCriteria'])==3


def test_unverified_parent_prose_cannot_supply_dimension_requests():
    excerpt='区分作者报告的结果、成立条件和未验证范围'
    original=plan(excerpt)
    result,changes=normalize_generated_requirements(original,ResearchQuestion(excerpt,['只解释第二点']),
        literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    assert result==original and not changes


@pytest.mark.parametrize('version',[1,2,3])
def test_actual_initial_plan_routes_new_dimension_policy_once(version):
    human='区分作者报告的结果、成立条件和未验证范围'
    record={'question':human,'requestGroundingContractVersion':version,'evidenceCoverageContractVersion':3,
            'planCompletionContractVersion':1,'materials':[{'materialId':'paper'}],'state':{'outputKind':'claim_verification'}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(plan(human))})
    make_plan_node(invoke,update,validate_plan)({'run_id':'r'});invoke.assert_called_once()
    criteria=record['state']['plan'][0]['obligations'][0]['completionCriteria']
    assert len(criteria)==(3 if version==3 else 1)


def test_compound_covered_response_cannot_waive_missing_fixed_dimension_verdicts():
    human='区分作者报告的结果、成立条件和未验证范围'
    old,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True)
    new,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    claim={'claimId':'c','kind':'reported','text':'某剪枝条件下质量接近。','evidenceRefs':['e']}
    verdict=[{'obligationId':'o','status':'covered','bindings':[{'claimId':'c','field':'text','excerpt':claim['text']}],
              'criteria':[{'criterionId':'human_aspect_1','responseType':'limitation','status':'covered',
                           'bindings':[{'claimId':'c','field':'text','excerpt':claim['text']}]}]}]
    assert not completion_criteria_gaps(old,[claim],verdict)
    gaps=completion_criteria_gaps(new,[claim],verdict)
    assert gaps['o']==['作者报告的结果','成立条件','未验证范围']


def test_audit_policy_is_optional_and_never_itself_grants_completion():
    human='区分作者报告的结果、成立条件和未验证范围'
    p,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    claim={'claimId':'c','kind':'reported','text':'某条件下质量接近。','evidenceRefs':['e']}
    prompts=[]
    def invoke(run,node,prompt,options,**kwargs): prompts.append(prompt);return {'content':'[]'}
    old=audit_final_answer('r',human,p,[claim],[],invoke,json.loads)
    new=audit_final_answer('r',human,p,[claim],[],invoke,json.loads,literal_dimensions=True)
    assert FINAL_DIMENSION_POLICY not in prompts[0] and FINAL_DIMENSION_POLICY in prompts[1]
    assert len(prompts)==2 and old['gaps'] and new['gaps']


@pytest.mark.parametrize('version',[2,3])
def test_both_initial_and_post_repair_final_audits_receive_frozen_policy(version,monkeypatch):
    human='核查质量并区分未验证范围'
    c={'claimId':'c','kind':'inference','text':'原草稿','evidenceRefs':['e']}
    record={'requestGroundingContractVersion':version,'question':human,
            'state':{'reportBody':{'claims':[c]},'evidence':[],'plan':plan(human)}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    seen=[]
    def audit(*args,**kwargs): seen.append(kwargs);return {'status':'checked','gaps':[]}
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',audit)
    monkeypatch.setattr('services.deep_research.repair.repair_rejected',lambda *a,**kw:[{**c,'text':'修订后的有界判断'}])
    verify=Mock(side_effect=[{'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},
                            {'accepted':[{**c,'text':'修订后的有界判断'}],'rejected':[]}])
    make_verify_node(verify,None,update,llm_invoke=lambda *a,**kw:{'content':'[]'})({'run_id':'r'})
    assert len(seen)==2
    assert all(kw.get('literal_dimensions',False) is (version==3) for kw in seen)


@pytest.mark.parametrize('value',[None,True,False,0,1,2,'3',4])
def test_dimension_policy_is_strict(value):
    assert not enabled({'requestGroundingContractVersion':value})
    assert enabled({'requestGroundingContractVersion':3})
