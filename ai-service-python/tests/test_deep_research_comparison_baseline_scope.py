from unittest.mock import Mock

import pytest

from services.deep_research.verification import precheck_claims, verify_claims


@pytest.fixture
def comparison():
    owner = {'sourceWorkId': 'paper', 'sourceVersionId': 'current', 'contentHash': 'hash',
             'location': {'page': 6, 'pageResolution': 'exact'},
             'verification': {'literal': 'passed'}, 'accessLevel': 'fulltext'}
    table = {**owner, 'evidenceId': 'typed', 'tableData': {
        'groups': [['Room', ['PSNR↑']]],
        'rows': [[1, 'Baseline [1]', ['20']], [2, 'Baseline∗[1]', ['22']],
                 [3, 'Compressed Baseline [2]', ['19']], [4, 'Ours', ['21']]],
    }, 'quote': 'Table row 1: Baseline [1] | 20\nTable row 2: Baseline∗[1] | 22\n'
                'Table row 3: Compressed Baseline [2] | 19\nTable row 4: Ours | 21'}
    plain = {**owner, 'evidenceId': 'plain',
             'quote': 'Baseline [1] 20\nBaseline∗[1] 22\nCompressed Baseline [2] 19\nOurs 21'}
    claim = {'claimId': 'point', 'kind': 'reported', 'detailLevel': 'fulltext',
             'evidenceRefs': ['plain'], 'text': '在 Room 上，相对原始 Baseline，PSNR 较高。'}
    return claim, plain, table


@pytest.mark.parametrize('text', ['相对原始 Baseline，PSNR 较高。', '相对 Baseline†，PSNR 较高。'])
def test_ambiguous_quality_trend_is_rejected_before_independent_review(comparison, text):
    claim, plain, table = comparison
    claim['text'] = text
    reviewer = Mock()
    outcome = verify_claims([claim], [plain, table], reviewer, comparison_baseline_scope=True)
    issue, = outcome['rejected']
    assert issue['reason'] == 'ambiguous_comparison_baseline'
    assert issue['baselineRows'] == ['Baseline [1]', 'Baseline∗[1]']
    reviewer.assert_not_called()
    assert precheck_claims([claim], [plain, table])['candidates'] == [claim]


@pytest.mark.parametrize('text', [
    '在 Room 上，相对未标星的 Baseline，PSNR 较高；相对 Baseline∗，PSNR 较低。',
    '在 Room 上，相对 Baseline [1]，PSNR 较高。',
    '在 Room 上，相对 Baseline（未标星），PSNR 较高。',
    '在 Room 上，相对 Compressed Baseline [2]，PSNR 较高。',
    '论文在 Room 上对 Baseline 报告了 PSNR。',
])
def test_unambiguous_row_or_no_direction_still_goes_to_scientific_review(comparison, text):
    claim, plain, table = comparison
    claim['text'] = text
    assert precheck_claims([claim], [plain, table], comparison_baseline_scope=True)['candidates'] == [claim]


@pytest.mark.parametrize('replace', [
    {'sourceVersionId': 'older', 'contentHash': 'older-hash'},
    {'location': {'page': 7, 'pageResolution': 'exact'}},
    {'quote': 'We discuss Baseline [1] and Baseline∗[1] in Room.'},
])
def test_uncited_or_foreign_tables_do_not_bind_baseline_scope(comparison, replace):
    claim, plain, table = comparison
    assert precheck_claims([claim], [{**plain, **replace}, table],
                           comparison_baseline_scope=True)['candidates'] == [claim]
