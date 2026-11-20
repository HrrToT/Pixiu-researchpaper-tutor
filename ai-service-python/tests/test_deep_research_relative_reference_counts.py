from unittest.mock import Mock

import pytest

from services.deep_research.measurement_numbers import measurement_numbers
from services.deep_research.verification import verify_claims
from test_deep_research_quantity_words import setup


@pytest.mark.parametrize('text', ['前一帧', '后一帧', '上一帧', '下一帧', '上一组', '下一个物体',
    '前一次实验', '后一个场景'])
def test_adjacent_item_reference_is_not_an_unreported_measurement(text):
    assert measurement_numbers(text, word_counts=True, relative_references=True) == set()
    assert measurement_numbers(text, word_counts=True) == {'1e0'}  # frozen spelling-v1


@pytest.mark.parametrize('text,expected', [('前两帧', {'2e0'}), ('后三组', {'3e0'}),
    ('测量一帧', {'1e0'}), ('前负一帧', {'-1e0'}), ('后正一个', {'1e0'}),
    ('延迟一帧', {'1e0'}), ('前一帧之后间隔四帧', {'4e0'}), ('前一帧相距3帧', {'3e0'})])
def test_actual_counts_signs_and_measurements_are_still_checked(text, expected):
    assert measurement_numbers(text, word_counts=True, relative_references=True) == expected


def test_relative_reference_fix_still_requires_own_semantic_evidence():
    c, ev = setup('新增高斯不传到下一帧。', 'Additional Gaussians are not used in subsequent frames.')
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    assert verify_claims([c], [ev], checker, quantity_spelling_version=2)['accepted']
    checker.assert_called_once()
    checker.reset_mock()
    assert verify_claims([c], [ev], quantity_spelling_version=2)['rejected'][0]['reason'] == 'semantic_unresolved'
    assert verify_claims([c], [ev], checker, quantity_spelling_version=1)['rejected'][0]['reason'] == 'numeric_mismatch'
    checker.assert_not_called()


def test_new_reference_policy_cannot_let_cited_one_support_wrong_count_or_disappear():
    c, ev = setup('前一帧包含2个物体。', 'One object is visible in the previous frame.')
    checker = Mock()
    rejection = verify_claims([c], [ev], checker, quantity_spelling_version=2)['rejected'][0]
    assert rejection['reason'] == 'numeric_mismatch' and rejection['missingReportedNumbers'] == ['2e0']
    checker.assert_not_called()
