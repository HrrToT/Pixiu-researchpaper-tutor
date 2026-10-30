from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.measurement_numbers import measurement_numbers
from services.deep_research.verification import precheck_claims, verify_claims
from test_deep_research_synthesis_premises import claim, evidence


@pytest.mark.parametrize('text', [
    '输入为一组图像及其时间标签。', '给定一组单目动态场景图像。',
    '从一组多视角照片重建场景。', '使用一组视频帧作为输入。',
])
def test_indefinite_image_collection_requires_no_invented_count(text):
    assert measurement_numbers(text, word_counts=True) == {'1e0'}
    assert measurement_numbers(text, word_counts=True, collection_articles=True) == set()


@pytest.mark.parametrize('text, expected', [
    ('只使用一组图像。', {'1e0'}), ('输入恰好一组图像。', {'1e0'}),
    ('输入为唯一一组图像。', {'1e0'}), ('总共使用一组图像。', {'1e0'}),
    ('使用至少一组图像。', {'1e0'}), ('使用一组图像而不是两组。', {'1e0', '2e0'}),
    ('使用1组图像。', {'1e0'}), ('使用三组图像。', {'3e0'}),
    ('使用一组实验结果。', {'1e0'}), ('使用一组样本。', {'1e0'}),
    ('训练一次，评估一帧。', {'1e0'}), ('输入为负一组图像。', {'-1e0'}),
    ('使用一组图像，共有十二张。', {'12e0'}),
])
def test_explicit_cardinality_and_experiment_counts_remain_checked(text, expected):
    assert measurement_numbers(text, word_counts=True, collection_articles=True) == expected


def test_actual_input_wording_keeps_sources_immutable_and_requires_semantics():
    source = [evidence('e', 'The input of our method is a set of images of a monocular dynamic scene.')]
    target = claim('输入为一组单目动态场景图像。')
    before = deepcopy((target, source))
    old = precheck_claims([target], source, quantity_spelling_version=5)
    assert old['rejected'][0]['missingReportedNumbers'] == ['1e0']
    check = Mock(return_value=[{'claimId':'c','status':'failed','reason':'Independent negative fixture'}])
    result = verify_claims([target], source, check, quantity_spelling_version=6)
    check.assert_called_once()
    assert result['rejected'][0]['reason'] == 'semantic_unresolved'
    assert (target, source) == before
    for text in ['输入为恰好一组图像。', '输入为三组图像。', '输入为一组图像，共十二张。']:
        check.reset_mock()
        result = verify_claims([claim(text)], source, check, quantity_spelling_version=6)
        assert result['rejected'][0]['reason'] == 'numeric_mismatch'
        check.assert_not_called()
