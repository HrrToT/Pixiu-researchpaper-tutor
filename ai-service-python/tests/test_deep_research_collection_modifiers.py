"""Indefinite geometric collections still require independent source support."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.measurement_numbers import without_collection_articles
from services.deep_research.verification import make_evidence, precheck_claims, verify_claims


def pair(text):
    quote = 'Our key idea is to collapse the 3D volume into a set of 2D oriented planar Gaussian disks.'
    evidence = make_evidence(
        {'workId': 'p', 'versionId': 'v', 'contentHash': 'h', 'accessLevel': 'fulltext'},
        quote, quote, location={'page': 2}, obligation_ids=['o'])
    claim = {'claimId': 'c', 'text': text, 'kind': 'reported',
             'evidenceRefs': [evidence['evidenceId']], 'conditions': {}, 'detailLevel': 'fulltext'}
    return claim, evidence


@pytest.mark.parametrize('text', [
    '2DGS把3D体积坍缩成一组在空间中定位的二维定向平面高斯盘。这些盘虽然本身是二维的，但每个盘在三维空间中有位置和朝向，因此整体能表示三维场景。',
    '2DGS将三维体积坍缩为一组在空间中定位的二维定向平面高斯盘；每个盘虽为二维，但具有三维位置和朝向，整体可表示三维场景。',
])
def test_saved_original_and_revision_reach_semantic_verification(text):
    claim, evidence = pair(text)
    before = deepcopy((claim, evidence))
    old = precheck_claims([claim], [evidence], quantity_spelling_version=13)
    assert old['rejected'][0]['reason'] == 'numeric_mismatch'
    assert not precheck_claims([claim], [evidence], quantity_spelling_version=14)['rejected']
    semantic = Mock(return_value=[{'claimId': 'c', 'status': 'unresolved',
                                  'reason': 'Representation must be supported by its own source'}])
    assert not verify_claims([claim], [evidence], semantic, quantity_spelling_version=14)['accepted']
    semantic.assert_called_once()
    assert (claim, evidence) == before


@pytest.mark.parametrize('description', [
    '在空间中定位的二维定向平面高斯盘',
    '具有相同朝向的平面高斯圆盘',
    '在空间中定位的具有相同朝向的高斯椭圆盘',
    '二维定向平面高斯盘片',
    '带朝向的表面片',
])
def test_relative_modifiers_do_not_make_indefinite_collection_a_measurement(description):
    text = '将场景表示为一组' + description
    assert without_collection_articles(text, geometric=2) == text.replace('一组', '组')


@pytest.mark.parametrize('text', [
    '实验采用一组在空间中定位的高斯盘',
    '将场景表示为仅一组在空间中定位的高斯盘',
    '仅将场景表示为一组在空间中定位的高斯盘',
    '总共将场景表示为一组在空间中定位的高斯盘',
    '将场景表示为1组在空间中定位的高斯盘',
    '将场景表示为两组在空间中定位的高斯盘',
    '将场景表示为负一组在空间中定位的高斯盘',
    '将场景表示为第一组在空间中定位的高斯盘',
    '将场景表示为一组高斯盘而非两组',
    '将场景表示为一组高斯圆盘参数',
    '将场景表示为一组高斯圆盘的参数',
    '将场景表示为一组高斯盘片参数',
    '将场景表示为一组二维高斯特征',
    '将场景表示为一组包含高斯重建结果的实验',
])
def test_actual_counts_and_non_geometric_objects_are_preserved(text):
    assert without_collection_articles(text, geometric=2) == text


@pytest.mark.parametrize('tail', ['，使用3个样本。', '，输出7维特征。', '，实验运行两次。'])
def test_other_quantities_survive_collection_normalization(tail):
    claim, evidence = pair('将场景表示为一组在空间中定位的高斯盘' + tail)
    assert precheck_claims([claim], [evidence], quantity_spelling_version=14)['rejected'][0]['reason'] == 'numeric_mismatch'


def test_legacy_geometry_mode_keeps_original_behavior():
    text = '将场景表示为一组在空间中定位的二维定向平面高斯盘'
    assert without_collection_articles(text, geometric=True) == text
    assert without_collection_articles(text, geometric=False) == text
