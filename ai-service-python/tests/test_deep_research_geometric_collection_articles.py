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


@pytest.mark.parametrize('verb',['用','使用','采用'])
def test_representation_use_is_an_indefinite_geometry_set_and_still_requires_semantics(verb):
    c,e=pair(f'3DGS v1{verb}一组3D高斯表示场景。','We represent the scene with 3D Gaussians.')
    assert precheck_claims([c],[e],quantity_spelling_version=15)['rejected']==[]
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Own evidence still required.'}])
    assert verify_claims([c],[e],semantic,quantity_spelling_version=15)['accepted']==[]
    semantic.assert_called_once()


def test_later_sentence_about_compression_does_not_make_a_representation_set_counted():
    text = '将场景表示为一组各向异性的三维高斯。点云压缩是未来方向，不是此处已报告的流程。'
    claim, evidence = pair(text, 'We optimize anisotropic 3D Gaussians. Point cloud compression is future work.')
    assert precheck_claims([claim], [evidence], quantity_spelling_version=25)['rejected'] == []

    counted = {**claim, 'text': text + '实验只使用一组。'}
    rejection, = precheck_claims([counted], [evidence], quantity_spelling_version=25)['rejected']
    assert rejection['reason'] == 'numeric_mismatch'


def test_representation_gloss_preserves_the_object_without_creating_a_group_count():
    text = '该方法用一组可优化的三维高斯（表示带属性区域的基本单元）表示场景。'
    claim, evidence = pair(text, 'Our scene representation consists of 3D Gaussians.')
    assert precheck_claims([claim], [evidence], quantity_spelling_version=25)['rejected'] == []
    counted = {**claim, 'text': text.replace('用一组', '用两组')}
    rejection, = precheck_claims([counted], [evidence], quantity_spelling_version=25)['rejected']
    assert rejection['missingReportedNumbers'] == ['2e0']


@pytest.mark.parametrize('text',[
    '本实验用一组3D高斯作为对照。','本实验采用一组3D高斯作为对照。',
    '本实验只用一组3D高斯表示场景。','本实验用唯一一组3D高斯表示场景。',
    '用1组3D高斯表示场景。','用两组3D高斯表示场景。',
    '用一组3D高斯表示场景，而不是两组。','用一组3D高斯表示场景，训练5个场景。',
    '用一组高斯参数表示场景。','用一组向量表示场景。'])
def test_representation_grammar_keeps_actual_groups_counts_and_features(text):
    c,e=pair(text,'We represent the scene with 3D Gaussians.')
    assert precheck_claims([c],[e],quantity_spelling_version=15)['rejected'][0]['reason']=='numeric_mismatch'
