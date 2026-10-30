from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.measurement_numbers import without_dimensional_labels
from services.deep_research.verification import precheck_claims,verify_claims
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('label',['二维表面片','二维的表面片','二维面片','三维表面元','二维片','2维薄片'])
def test_spatial_surface_labels_are_not_empirical_measurements_but_still_need_semantic_evidence(label):
    c,e=pair(label+'的法线与深度图估计的法线对齐。');before=deepcopy((c,e))
    assert precheck_claims([c],[e],quantity_spelling_version=10)['rejected'][0]['reason']=='numeric_mismatch'
    assert not precheck_claims([c],[e],quantity_spelling_version=11)['rejected']
    checker=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'Spatial identity still needs its own source support.'}])
    assert not verify_claims([c],[e],checker,quantity_spelling_version=11)['accepted']
    checker.assert_called_once();assert (c,e)==before


@pytest.mark.parametrize('text',['负二维片','第二维表面片','二维片特征向量','二维片段编码','二维向量','三维输出'])
def test_feature_dimensions_signed_values_and_ordinals_remain_quantity_candidates(text):
    assert without_dimensional_labels(text,surface_labels=2)==text


@pytest.mark.parametrize('text',['二维表面片用了2个样本。','二维片有3个通道。','二维面片是7维向量。','模型压缩十五倍。'])
def test_surface_label_does_not_authorize_other_measured_numbers(text):
    c,e=pair(text)
    assert precheck_claims([c],[e],quantity_spelling_version=11)['rejected'][0]['reason']=='numeric_mismatch'


def test_surface_label_in_source_cannot_supply_an_empirical_count_in_answer():
    c,e=pair('用了2个样本。','二维表面片的法线与表面法线对齐。')
    assert precheck_claims([c],[e],quantity_spelling_version=11)['rejected'][0]['reason']=='numeric_mismatch'
