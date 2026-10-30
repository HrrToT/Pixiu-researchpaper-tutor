from copy import deepcopy
import pytest
from services.deep_research.coverage_repair import prepare_coverage_repair


def example():
    claims=[{'claimId':f'c{i}','text':f'point{i}','obligationIds':[f'o{i}']} for i in (1,2,3)]
    verified={'accepted':claims[1:],'rejected':[{'claimId':'c1','reason':'numeric_mismatch'}]}
    specific={'obligationId':'o1','question':'Explain point1'}
    whole={'obligationId':'answer_scope','question':'Explain all three points','wholeQuestion':True}
    audit={'status':'checked','requestCoverageContractVersion':3,'gaps':[whole,specific],
           'verdicts':[{'obligationId':'answer_scope','status':'partial','bindings':[{'claimId':'c2'},{'claimId':'c3'}]},
                       {'obligationId':'o1','status':'missing','bindings':[]},
                       {'obligationId':'o2','status':'covered','bindings':[{'claimId':'c2'}]},
                       {'obligationId':'o3','status':'covered','bindings':[{'claimId':'c3'}]}]}
    return {'claims':claims},verified,audit


def test_specific_rejected_point_is_repaired_without_rewriting_covered_points_or_waiving_whole_audit():
    report,verified,audit=example();before=deepcopy((report,verified,audit))
    old=prepare_coverage_repair(report,verified,audit)
    new=prepare_coverage_repair(report,verified,audit,prioritize_specific=True)
    assert {r['claimId'] for r in old['rejected']}=={'c1','c2','c3'}
    assert [r['claimId'] for r in new['rejected']]==['c1']
    assert new['accepted']==verified['accepted']
    assert new['rejected'][0]['reason']=='numeric_mismatch'
    assert 'Explain all three points' in new['rejected'][0]['missingQuestions']
    assert (report,verified,audit)==before and audit['gaps'][0]['wholeQuestion']


def test_whole_question_only_gap_still_schedules_existing_answer_for_repair():
    report,verified,audit=example();audit['gaps']=audit['gaps'][:1]
    new=prepare_coverage_repair(report,verified,audit,prioritize_specific=True)
    assert {r['claimId'] for r in new['rejected']}=={'c1','c2','c3'}


def test_partial_accepted_point_is_still_selected_for_its_specific_missing_requirement():
    report,verified,audit=example()
    audit['gaps'][1]={'obligationId':'o2','question':'Complete point2'}
    audit['verdicts'][2]['status']='partial'
    new=prepare_coverage_repair(report,verified,audit,prioritize_specific=True)
    assert {r['claimId'] for r in new['rejected']}=={'c1','c2'}
    assert [r['claimId'] for r in new['accepted']]==['c3']


def test_unknown_specific_requirement_keeps_conservative_fallback():
    report,verified,audit=example();audit['gaps'][1]={'obligationId':'foreign','question':'Unmapped actual requirement'}
    new=prepare_coverage_repair(report,verified,audit,prioritize_specific=True)
    assert {r['claimId'] for r in new['rejected']}=={'c1','c2','c3'}


@pytest.mark.parametrize('value',[None,1,'true'])
def test_scheduling_policy_requires_explicit_boolean(value):
    with pytest.raises(ValueError):prepare_coverage_repair(*example(),prioritize_specific=value)
