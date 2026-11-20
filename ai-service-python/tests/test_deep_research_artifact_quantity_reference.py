from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.measurement_numbers import measurement_numbers
from services.deep_research.verification import verify_claims
from test_deep_research_quantity_words import setup


@pytest.mark.parametrize('text,expected', [
 ('它输出一个7维向量。',{'7e0'}),('结果是一个七维向量。',{'7e0'}),
 ('它会输出一组数字，前三个数字表示移动。',{'3e0'}),('映射为一组特征。',set()),
 ('产生一个矩阵。',set()),('它输出一个7维向量，然后传给下一帧。',{'7e0'}),
])
def test_an_output_artifact_reference_is_not_an_extra_measured_one(text,expected):
    assert measurement_numbers(text,word_counts=True,relative_references=True,artifact_references=True)==expected
    assert '1e0' in measurement_numbers(text,word_counts=True,relative_references=True)


@pytest.mark.parametrize('text,expected', [
 ('只输出一个7维向量',{'1e0','7e0'}),('仅输出了一组数字',{'1e0'}),
 ('只能生成一组特征',{'1e0'}),('输出恰好一个向量',{'1e0'}),
 ('输出1个7维向量',{'1e0','7e0'}),('输出负一个向量',{'-1e0'}),
 ('输出两组数字',{'2e0'}),('输出一个样本',{'1e0'}),('得到一组实验结果',{'1e0'}),
 ('使用一组视角',{'1e0'}),('训练一次',{'1e0'}),('评估一帧',{'1e0'}),
 ('这一个向量包含4个分量',{'1e0','4e0'}),
])
def test_actual_cardinality_and_experimental_counts_still_use_exact_numeric_checks(text,expected):
    assert measurement_numbers(text,word_counts=True,relative_references=True,artifact_references=True)==expected


def test_artifact_fix_does_not_promote_remaining_dimension_arithmetic():
    c,e=setup('它输出一个7维向量，前三维是平移，后四维是旋转。')
    checker=Mock()
    rejection=verify_claims([c],[e],checker,quantity_spelling_version=3)['rejected'][0]
    assert rejection['missingReportedNumbers']==['4e0'];checker.assert_not_called()
    assert verify_claims([c],[e],quantity_spelling_version=2)['rejected'][0]['missingReportedNumbers']==['1e0','4e0']


def test_plain_group_of_numbers_still_requires_semantics_and_keeps_original_data():
    c,e=setup('它输出一组数字，前三个数字表示平移。');original=deepcopy([c,e])
    negative=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Negative fixture'}])
    result=verify_claims([c],[e],negative,quantity_spelling_version=3)
    assert result['rejected'][0]['reason']=='semantic_unresolved';negative.assert_called_once()
    assert [c,e]==original
    negative.reset_mock()
    assert verify_claims([c],[e],negative,quantity_spelling_version=2)['rejected'][0]['reason']=='numeric_mismatch'
    negative.assert_not_called()
