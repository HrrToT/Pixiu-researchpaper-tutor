from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.measurement_numbers import without_dimensional_labels
from services.deep_research.verification import precheck_claims,verify_claims
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('label',['二维基元','二维网格','三维原语','二维表示单元','三维构形','四维流形','二维表面元素'])
def test_spatial_labels_are_not_limited_to_a_list_of_geometry_object_names(label):
    c,e=pair(label+'沿表面分布。');before=deepcopy((c,e))
    checker=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'Its dimensional identity still needs semantic support.'}])
    assert not precheck_claims([c],[e],quantity_spelling_version=13)['rejected']
    assert not verify_claims([c],[e],checker,quantity_spelling_version=13)['accepted']
    checker.assert_called_once();assert (c,e)==before


@pytest.mark.parametrize('text',['二维向量','三维输出','2维特征','四维张量','二维编码','二维的参数',
    '将特征降为二维空间','向量投影到三维','输出是二维','潜变量压缩到三维空间',
    '特征仅有二维','第二维基元','负二维原语','±二维基元'])
def test_explicit_dimension_values_ordinals_and_signs_remain_numeric(text):
    assert without_dimensional_labels(text,surface_labels=3)==text


@pytest.mark.parametrize('text',['二维基元用了3个样本。','三维原语有7维特征。','五维原语沿表面分布。'])
def test_spatial_label_does_not_hide_other_quantities_or_higher_dimensional_values(text):
    c,e=pair(text)
    assert precheck_claims([c],[e],quantity_spelling_version=13)['rejected'][0]['reason']=='numeric_mismatch'


def test_version_twelve_keeps_its_previous_geometry_name_scope():
    c,e=pair('二维基元沿表面分布。')
    assert precheck_claims([c],[e],quantity_spelling_version=12)['rejected'][0]['reason']=='numeric_mismatch'
