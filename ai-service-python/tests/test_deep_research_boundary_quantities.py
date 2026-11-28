from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.boundary_quantities import failures,GUIDANCE
from services.deep_research.scope_expression import materialize,guidance,review_expression
from services.deep_research.tools import BudgetedSemanticChecker

C={'claimId':'c','kind':'inference','text':'bounded','evidenceRefs':['e'],'conditions':{}}
E=[{'evidenceId':'e','quote':'Score 0.3 is reported. The value 0.3 has no physical unit.','sourceContext':{}}]
def expr(text):return {'c':{'observedSettings':[],'notEstablished':[text]}}

@pytest.mark.parametrize('text',['误差差距小于0.3 dB','gap less than 0.3 dB','error < 0.30 dB','误差不超过3e-1 dB'])
def test_unrelated_equal_numeric_cell_does_not_anchor_a_unit_threshold(text):
    before=deepcopy((C,E))
    out=failures([C],expr(text),E,'解释质量是否接近')
    assert out[0]['reason']=='unanchored_boundary_quantity' and out[0]['unanchoredQuantities'][0]['unit'].casefold()=='db'
    assert before==(C,E)


def test_own_original_or_human_quantity_is_only_an_anchor_not_approval():
    assert failures([C],expr('error <0.30 dB'),E,'检查误差小于0.3 dB能否推广')==[]
    assert failures([C],expr('error <0.30 dB'),[{**E[0],'quote':'Criterion 0.3 dB is explicitly stated.'}],'检查范围')==[]
    assert failures([C],expr('error <0.3 dB'),[{**E[0],'sourceContext':E[0]['quote']+' Criterion 0.3 dB.'}],'检查范围')==[]
    foreign=[*E,{'evidenceId':'foreign','quote':'Criterion 0.3 dB'}]
    assert failures([C],expr('error <0.3 dB'),foreign,'检查范围')
    assert failures([C],expr('error <0.3 dB'),[{**E[0],'quote':'Criterion 0.3 MB'}],'检查范围')
    assert not failures([C],expr('3DGS和方法v2在其他设置中仍接近'),E,'检查范围')


@pytest.mark.parametrize('partitioned',[False,True])
def test_invalid_boundary_is_rejected_before_any_model_call_on_initial_and_repair_paths(partitioned):
    invoke=Mock()
    checker=BudgetedSemanticChecker(invoke,'r',research_question='检查范围',scope_expression_context=lambda cs:{k:v for k,v in expr('error <0.3 dB').items() if k in {c['claimId'] for c in cs}},partitioned_scope_review=partitioned,boundary_quantity_grounding=True)
    first=checker([C],E);repair=checker.check_revisions([C],E,[])
    assert first==repair and first[0]['status']=='failed' and first[0]['reason']=='unanchored_boundary_quantity'
    invoke.assert_not_called()


def test_anchor_cannot_override_an_independent_failed_verdict_or_opt_old_run_in():
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'fixture: unrelated criterion'}])})
    checker=BudgetedSemanticChecker(invoke,'r',research_question='criterion <0.3 dB',scope_expression_context=lambda _:expr('error <0.3 dB'),boundary_quantity_grounding=True)
    assert checker([C],E)[0]['status']=='failed' and invoke.call_count==1
    invoke.reset_mock()
    legacy=BudgetedSemanticChecker(invoke,'r',research_question='检查范围',scope_expression_context=lambda _:expr('error <0.3 dB'))
    assert legacy([C],E)[0]['status']=='failed' and invoke.call_count==1


def test_version_four_preserves_operator_rendering_and_refuses_to_suggest_invented_tolerance():
    raw={**C,'text':'','scopeExpression':{'observedSettings':[],'notEstablished':[{'quantifier':'all','domain':'其他设置','subject':'方法','comparator':'基线','predicate':'质量接近'}]}}
    assert materialize(raw,4)==materialize(raw,3)
    assert review_expression(raw['scopeExpression'],4)==review_expression(raw['scopeExpression'],3)
    assert GUIDANCE in guidance(4) and 'including metric and tolerance where applicable' not in guidance(4)
    assert GUIDANCE not in guidance(3)


def test_pathological_model_number_is_rejected_without_crashing():
    assert failures([C],expr('error <1e9999999999999999999999 dB'),E,'检查范围')


def test_scalar_criterion_does_not_take_a_following_english_word_as_a_unit():
    assert not failures([C],expr('score less than 0.3 in other settings'),E,'检查范围')
    assert failures([C],expr('size <0.3 MB'),[{**E[0],'quote':'value 0.3 Mb'}],'检查范围')


def test_scope_four_required_role_survives_repair_and_cannot_reuse_a_scope_three_checkpoint():
    from services.deep_research.repair import repair_rejected
    from services.deep_research.contracts import DeepResearchError
    from test_deep_research_quantified_scope import quantified
    raw=quantified();original,_=materialize(raw,4)
    report={'claims':[original]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    evidence=[{'evidenceId':'e','quote':'Observed quality.','accessLevel':'fulltext'}]
    raw['evidenceRefs']=['E1'];invoke=Mock(return_value={'content':json.dumps([raw])});states=[]
    kw={'scope_expression':4,'claim_check':9,'required_scope_ids':['c']}
    revised=repair_rejected(report,checks,evidence,'解释范围',invoke,json.loads,checkpoint=states.append,**kw)
    assert revised and revised[0]['text'].startswith('已报告设置')
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(report,checks,evidence,'解释范围',invoke,json.loads,batch_state=saved,**kw)==revised
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,evidence,'解释范围',invoke,json.loads,batch_state=saved,**{**kw,'scope_expression':3})
    invoke.assert_not_called()
