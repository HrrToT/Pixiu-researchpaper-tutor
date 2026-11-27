from copy import deepcopy

import pytest

from core.pdf_threshold_tables import _ruled_tables


def _fixture():
    lines = [
        (24, [(80, 'Matching'), (150, 'Error')]),
        (38, [(80, 'ϵ'), (84, '='), (91, '1'), (108, 'ϵ'), (112, '='), (119, '3'), (150, 'RMSE')]),
        (53, [(35, 'Method-A'), (82, '.340'), (110, '.684'), (150, '1.158')]),
        (64, [(35, 'Method-B'), (82, '.430'), (110, '.676'), (150, '0.833')]),
        (89, [(29, 'Table'), (48, '3.'), (63, 'Reference'), (100, 'matches.')]),
    ]
    runs = [{'x': x, 'y': y, 'text': text, 'tokens': [{'x': x, 'text': text}]}
            for y, tokens in lines for x, text in tokens]
    rules = [(34, 174, y) for y in (16, 30, 45, 75)]
    plain = 'Matching Error\nϵ = 1 ϵ = 3 RMSE\nMethod-A .340 .684 1.158\nMethod-B .430 .676 0.833\nTable 3. Reference matches.'
    return runs, rules, plain


def test_recovers_only_physically_aligned_threshold_columns():
    table, = _ruled_tables(*_fixture())
    assert table == {
        'number': '3',
        'caption': 'Table 3. Reference matches.',
        'thresholdProjection': True,
        'tableData': {
            'groups': [['Matching', ['ϵ=1', 'ϵ=3']]],
            'rows': [[2, 'Method-A', ['0.340', '0.684']], [3, 'Method-B', ['0.430', '0.676']]],
        },
    }


@pytest.mark.parametrize('fault', ['unbound_caption', 'row_mismatch', 'shell_rule_missing', 'cell_shift', 'header_shift'])
def test_rejects_unverified_threshold_tables(fault):
    runs, rules, plain = deepcopy(_fixture())
    if fault == 'unbound_caption':
        plain = plain.replace('Table 3.', 'Table 4.')
    elif fault == 'row_mismatch':
        plain = plain.replace('.340 .684', '.684 .340')
    elif fault == 'shell_rule_missing':
        rules.pop(1)
    else:
        row = next(run for run in runs if run['text'] == ('.684' if fault == 'cell_shift' else '3'))
        row['x'] = row['tokens'][0]['x'] = 90
    assert list(_ruled_tables(runs, rules, plain)) == []


def test_threshold_table_uses_one_result_slot_for_a_benchmark_named_by_the_user():
    from services.deep_research.measurement_table_navigation import (
        requested_threshold_benchmarks, retain_threshold_table,
    )

    selected = [{'sourceId': 'best'}, {'sourceId': 'context', 'contextForSourceId': 'best'},
                {'sourceId': 'last'}]
    table = {'sourceId': 't3', 'text': 'Table caption: Table 3. HPatches matching. FeatureNet results.',
             'location': {'thresholdColumnsVerified': True}}
    other = {**table, 'sourceId': 't4', 'text': 'Table caption: Table 4. ImageNet matching.'}
    result_query = 'FeatureNet HPatches quantitative results'
    requested = requested_threshold_benchmarks('给出 hpatches 数据集的两个结果', result_query)
    assert requested == {'hpatches'}
    assert retain_threshold_table(selected, [table, other], requested, 3) == [
        selected[0], table, selected[1],
    ]
    assert retain_threshold_table(selected, [table, {**table, 'sourceId': 't5'}], requested, 3) == selected
    assert requested_threshold_benchmarks('解释 HPatches 数据处理', 'HPatches training stages') == set()
    assert requested_threshold_benchmarks('给出 FeatureNet 的结果', 'HPatches quantitative results') == set()
