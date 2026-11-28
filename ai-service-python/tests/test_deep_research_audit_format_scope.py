from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.comparison_reasoning import normalize_audit_scope,validate_audit,audit_prompt
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims
from test_deep_research_comparison_reasoning import inputs,audit
from test_deep_research_absence_scope import fixture


@pytest.mark.parametrize('value', ['cross_study: measurement conditions', 'cross_study：测量条件'])
def test_enum_annotation_normalization_preserves_every_semantic_field_and_raw_input(value):
    c,e=inputs();v={'claimId':'c','status':'passed','reason':'fixture','comparisonAudit':audit(e)}
    v['comparisonAudit']['scope']=value;before=deepcopy(v)
    fixed=normalize_audit_scope(c,v,e,version=2)
    assert v==before and fixed['status']==v['status'] and fixed['reason']==v['reason']
    assert fixed['comparisonAudit']=={**v['comparisonAudit'],'scope':'cross_study'}
    assert fixed['comparisonAuditNormalization']=={'field':'scope','original':value,'normalized':'cross_study'}
    assert not validate_audit(c,fixed,e)
    assert validate_audit(c,v,e)==['comparison_premise_not_established']
    assert normalize_audit_scope(c,v,e,version=1)==v


@pytest.mark.parametrize('value', ['within_study: conditions','cross_study','cross_study:',
    'cross_study: within_study','cross_study or within_study','CROSS_STUDY: conditions',
    'cross_study: first\nsecond','cross_study: '+ 'x'*301, ['cross_study']])
def test_wrong_ambiguous_or_non_string_scope_is_never_guessed(value):
    c,e=inputs();v={'comparisonAudit':{**audit(e),'scope':value}}
    assert normalize_audit_scope(c,v,e,version=2)==v


@pytest.mark.parametrize('change',['wrong_quote','missing_source','supports_false','different_without_pair'])
def test_corrected_enum_does_not_bypass_other_audit_failures(change):
    c,e=inputs();a={**audit(e),'scope':'cross_study: source conditions'}
    if change=='wrong_quote': a['premises'][0]['quote']='invented'
    elif change=='missing_source': a['premises']=a['premises'][:1]
    elif change=='supports_false': a['supportsClaim']=False
    else: a['alignment']='different'
    v=normalize_audit_scope(c,{'comparisonAudit':a},e,version=2)
    assert validate_audit(c,v,e)


def test_checker_normalizes_before_all_checks_without_extra_provider_call():
    c,e=inputs();sent=[]
    def invoke(**kw):
        sent.append(kw)
        return {'content':json.dumps([{'claimId':'c','status':'passed','reason':'fixture',
            'comparisonAudit':{**audit([{'evidenceId':f'E{i+1}','quote':ev['quote']} for i,ev in enumerate(e)]),
                               'scope':'cross_study: settings'}}])}
    checker=BudgetedSemanticChecker(invoke,'r',comparison_reasoning=True,comparison_audit_version=2)
    verdict=checker([c],e)[0]
    assert verdict['status']=='passed' and len(sent)==1
    assert verdict['comparisonAuditNormalization']['original']=='cross_study: settings'
    assert 'scope field is an ENUM' in sent[0]['prompt']
    assert 'scope field is an ENUM' not in audit_prompt({'c':'cross_study'},1)


@pytest.mark.parametrize('text', [
    '未验证范围：有限观察不足以证明所有场景均有效。',
    '有限观察不能证明未测试维度上质量仍接近。',
    '有限观察不足以证明未验证的条件下仍有效。',
])
def test_nonassertive_absence_routes_to_independent_semantics(text):
    c,e=fixture(text);check=Mock(return_value=[{'claimId':'c','status':'failed','reason':'fixture'}])
    assert verify_claims([c],[e],check,absence_scope_version=4)['rejected'][0]['reason']=='semantic_unresolved'
    check.assert_called_once()
    assert verify_claims([c],[e],absence_scope_version=3)['rejected'][0]['reason']=='absence_not_established'
    assert not verify_claims([c],[e],absence_scope_version=4)['accepted']


@pytest.mark.parametrize('text', [
    '未验证范围：作者未验证其他场景。',
    '未验证范围：论文没有报告其他硬件。',
    '作者未测试其他维度，所以不能证明泛化。',
    '不能证明泛化，但作者未测试其他维度。',
    '未验证其他条件。',
])
def test_nominal_label_cannot_hide_a_real_author_absence_assertion(text):
    c,e=fixture(text);check=Mock()
    assert verify_claims([c],[e],check,absence_scope_version=4)['rejected'][0]['reason']=='absence_not_established'
    check.assert_not_called()
