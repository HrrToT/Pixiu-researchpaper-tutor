from unittest.mock import Mock

import pytest

from services.deep_research.verification import verify_claims


def evidence(quote='The method is evaluated on one scene.'):
    return {'evidenceId': 'e', 'quote': quote, 'accessLevel': 'fulltext',
            'verification': {'literal': 'passed'}}


def claim(text, **kwargs):
    return {'claimId': 'c', 'kind': 'proposal', 'text': text, 'evidenceRefs': ['e'], **kwargs}


@pytest.mark.parametrize('text', ['由于论文未提供原始划分，本方案另作划分。',
    '当前取得片段可作参考，但论文没有报告其他场景。',
    '所选证据未提供配置。论文未提供硬件信息。',
    'The paper does not report a split; we propose a new one.'])
def test_proposal_label_or_a_scoped_neighbor_cannot_hide_a_paper_wide_absence_fact(text):
    check = Mock()
    result = verify_claims([claim(text)], [evidence()], check)
    assert result['rejected'][0]['reason'] == 'absence_not_established'
    check.assert_not_called()


def test_conditions_are_checked_as_user_visible_facts_too():
    result = verify_claims([claim('拟议单场景实验。', conditions={'理由': '论文未报告其他场景'})], [evidence()])
    assert result['rejected'][0]['reason'] == 'absence_not_established'


@pytest.mark.parametrize('text', ['所选证据未提供原始划分，本方案另作划分。',
    '当前取得的论文片段未提供硬件信息。', '本实验不包含跨场景泛化检验。'])
def test_bounded_limitation_or_proposed_scope_still_requires_independent_verification(text):
    c, e = claim(text), evidence()
    assert not verify_claims([c], [e])['accepted']
    assert verify_claims([c], [e], lambda *_: [{'claimId': 'c', 'status': 'passed'}])['accepted']


def test_explicit_negative_source_is_not_a_truth_verdict_or_a_subject_match():
    c = claim('论文未报告跨场景结果。')
    e = evidence('We do not evaluate across scenes.')
    assert not verify_claims([c], [e])['accepted']
    assert verify_claims([c], [e], lambda *_: [{'claimId': 'c', 'status': 'passed'}])['accepted']
    assert not verify_claims([c], [e], lambda *_: [{'claimId': 'c', 'status': 'failed'}])['accepted']


@pytest.mark.parametrize('text', ['依据E1表6选择场景。', '见 E1。', 'P2介绍了该方法。',
    '证据E1支持该结论。', '来源为ev_' + 'a' * 64])
def test_internal_reference_leak_is_rejected_before_a_semantic_call(text):
    check = Mock()
    result = verify_claims([claim(text)], [evidence()], check)
    assert result['rejected'][0]['reason'] == 'internal_reference_in_prose'
    check.assert_not_called()


def test_conditions_cannot_leak_aliases_but_arxiv_and_legitimate_source_symbols_survive():
    e = evidence('The energy E1 is minimized. We use 3D Gaussian primitives.')
    result = verify_claims([claim('拟议比较。', conditions={'依据': 'E2表6'})], [e])
    assert result['rejected'][0]['reason'] == 'internal_reference_in_prose'
    valid = claim('以 E1 能量作为目标，PE1作为本地变量名；arXiv:2408.14823v2。')
    assert verify_claims([valid], [e], lambda *_: [{'claimId': 'c', 'status': 'passed'}])['accepted']
