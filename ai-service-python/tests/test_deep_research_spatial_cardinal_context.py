from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.measurement_numbers import without_dimensional_labels
from services.deep_research.verification import precheck_claims, verify_claims
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('predicate', ['共同表示', '共享', '共面分布于', '共线排列于'])
def test_compound_predicates_do_not_turn_spatial_labels_into_totals(predicate):
    text = '二维基元' + predicate + '三维场景。'
    assert '三维' in without_dimensional_labels(text, surface_labels=3)
    assert without_dimensional_labels(text, surface_labels=4) == '基元' + predicate + '场景。'


def test_actual_saved_claim_needs_semantic_review_after_numeric_false_positive_is_removed():
    text = '这里的“2D”指每个基元是二维高斯椭圆盘，但通过在世界坐标系中定位和定向，并沿光线进行体积渲染，这些二维基元共同表示三维场景。'
    claim, evidence = pair(text)
    before = deepcopy((claim, evidence))
    assert precheck_claims([claim], [evidence], quantity_spelling_version=14)['rejected'][0]['reason'] == 'numeric_mismatch'
    assert not precheck_claims([claim], [evidence], quantity_spelling_version=15)['rejected']
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'unresolved', 'reason': 'Check representation against its own source'}])
    assert not verify_claims([claim], [evidence], checker, quantity_spelling_version=15)['accepted']
    checker.assert_called_once()
    assert (claim, evidence) == before


@pytest.mark.parametrize('prefix', ['共', '共计', '共有', '共使用', '共计采用了', '共包含', '总共', '仅有', '至少'])
def test_explicit_totals_remain_numeric(prefix):
    text = prefix + '三维空间'
    assert without_dimensional_labels(text, surface_labels=4) == text


@pytest.mark.parametrize('text', ['共享三维参数', '共同输出三维向量', '共用二维特征',
                                  '将特征共同映射到三维空间', '三维输出', '第二维基元', '负三维场景'])
def test_numeric_roles_ordinals_and_signs_remain_checked(text):
    assert without_dimensional_labels(text, surface_labels=4) == text


@pytest.mark.parametrize('tail', ['使用3个样本。', '拥有7维特征。', '采用两组高斯。'])
def test_compound_predicate_cannot_hide_other_quantities(tail):
    claim, evidence = pair('二维基元共同表示三维场景，' + tail)
    assert precheck_claims([claim], [evidence], quantity_spelling_version=15)['rejected'][0]['reason'] == 'numeric_mismatch'
