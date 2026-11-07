from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.measurement_numbers import without_collection_articles
from services.deep_research.verification import precheck_claims,verify_claims
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('text',['将体积坍缩为一组有方向的平面高斯圆盘。',
    '将场景表示为一组2D高斯基元。','将曲面近似为一组定向的椭圆盘。'])
def test_definitional_introduction_of_geometry_set_is_not_a_measured_group_count(text):
    c,e=pair(text,'We collapse the volume into a set of oriented planar Gaussian disks.')
    before=deepcopy((c,e))
    assert precheck_claims([c],[e],quantity_spelling_version=11)['rejected'][0]['reason']=='numeric_mismatch'
    assert not precheck_claims([c],[e],quantity_spelling_version=12)['rejected']
    check=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'Definition must still be supported by its own source.'}])
    assert not verify_claims([c],[e],check,quantity_spelling_version=12)['accepted']
    check.assert_called_once();assert (c,e)==before


@pytest.mark.parametrize('text',['本实验采用一组高斯作为对照。','将体积只表示为一组高斯圆盘。',
    '将体积坍缩为1组高斯圆盘。','将体积坍缩为两组高斯圆盘。',
    '将体积坍缩为一组高斯圆盘，而不是两组。','将特征表示为一组向量。',
    '将状态表示为一组高斯参数。','将体积坍缩为一组高斯圆盘，训练3个场景。'])
def test_experiment_counts_explicit_cardinals_feature_groups_and_other_numbers_stay_checked(text):
    c,e=pair(text,'We represent surfaces with Gaussian disks.')
    assert precheck_claims([c],[e],quantity_spelling_version=12)['rejected'][0]['reason']=='numeric_mismatch'


def test_definitional_set_in_source_does_not_license_a_measured_group_count():
    c,e=pair('本实验只使用一组。','将体积坍缩为一组平面高斯圆盘。')
    assert precheck_claims([c],[e],quantity_spelling_version=12)['rejected'][0]['reason']=='numeric_mismatch'


def test_legacy_normalization_keeps_geometry_set_words_unchanged():
    text='将体积坍缩为一组平面高斯圆盘。'
    assert without_collection_articles(text)==text
    assert without_collection_articles(text,geometric=True)!=text
