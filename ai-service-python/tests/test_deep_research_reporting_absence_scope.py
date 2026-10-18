from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.verification import verify_claims
from test_deep_research_absence_scope import fixture


@pytest.mark.parametrize('text', [
 '作者未在其他数据集或指标上验证接近性，因此不能泛化。',
 '基于上述数据，作者未在其他数据集或指标上验证接近性。',
 '当前取得的片段可以参考，但作者没有对其他场景进行评估。',
 '论文未能给出跨硬件评测。',
])
def test_intervening_scope_words_cannot_hide_an_author_wide_absence_claim(text):
    c,e=fixture(text);before=deepcopy([c,e]);checker=Mock()
    result=verify_claims([c],[e],checker,absence_scope_version=2)
    assert result['rejected'][0]['reason']=='absence_not_established'
    assert '本次引用' in result['rejected'][0]['detail']
    checker.assert_not_called();assert [c,e]==before


def test_old_scope_and_diagnostic_shape_remain_frozen():
    c,e=fixture('作者未在其他数据集验证。')
    assert verify_claims([c],[e],absence_scope_version=1)['rejected'][0]['reason']=='semantic_unresolved'
    c['text']='论文没有报告其他场景。'
    assert verify_claims([c],[e],absence_scope_version=1)['rejected']==[{'claimId':'c','reason':'absence_not_established'}]


def test_unrelated_method_negation_does_not_establish_missing_research():
    c,e=fixture('论文没有报告其他场景的验证。')
    e['quote']='We do not optimize opacity during this stage.'
    checker=Mock()
    assert verify_claims([c],[e],checker,absence_scope_version=2)['rejected'][0]['reason']=='absence_not_established'
    checker.assert_not_called()
    assert verify_claims([c],[e],absence_scope_version=1)['rejected'][0]['reason']=='semantic_unresolved'


@pytest.mark.parametrize('quote', ['We did not evaluate on other hardware.',
    'We have not yet tested across scenes.', '我们没有在其他硬件上进行评估。', '论文未提供跨硬件测试结果。',
    'We do not provide hardware configuration.', 'We do not give the raw split.', '我们未能提供源数据。'])
def test_explicit_reporting_absence_still_needs_independent_subject_and_scope_verification(quote):
    c,e=fixture('作者没有报告跨硬件测试结果。');e['quote']=quote
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Negative fixture checks the exact scope'}])
    result=verify_claims([c],[e],checker,absence_scope_version=2)
    assert result['rejected'][0]['reason']=='semantic_unresolved';checker.assert_called_once()
    assert not verify_claims([c],[e],absence_scope_version=2)['accepted']


def test_bounded_evidence_absence_and_negative_method_premise_remain_semantically_checked():
    for text in ['当前取得的论文片段未在其他场景提供验证。', '初始帧中不存在新出现物体。']:
        c,e=fixture(text);checker=Mock(return_value=[{'claimId':'c','status':'failed'}])
        assert verify_claims([c],[e],checker,absence_scope_version=2)['rejected'][0]['reason']=='semantic_unresolved'
        checker.assert_called_once()
