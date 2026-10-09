from copy import deepcopy
import json

import pytest

from services.comparison_measurements import bounded_table_body, validate_numeric_comparison
from services.research_synthesis import validate_claim


PACKET = {'groups': [['Alpha Dataset', ['FPS', 'Size']], ['Beta Dataset', ['FPS', 'Size']]],
          'rows': [[2, 'Baseline *', ['100', '100MB', '300', '90MB']],
                   [3, 'Ours', ['200', '20MB', '400', '30MB']]]}
BASE = 'Table row 2: Baseline * | 100 | 100MB | 300 | 90MB'
OURS = 'Table row 3: Ours | 200 | 20MB | 400 | 30MB'


def fixture():
    table = {'sourceId': 't', 'pdfId': 'A', 'text': BASE + '\n' + OURS,
             'metadata': {'evidence_kind': 'table', 'table_verified_data': json.dumps(PACKET)},
             '_verifiedTable': deepcopy(PACKET)}
    hardware = {'sourceId': 'h', 'pdfId': 'A', 'text': 'All measurements were performed on GPU A.'}
    measurement = {'sourceId': 't', 'row': 3, 'group': 0, 'metric': 'FPS', 'value': '200',
                   'baselineRow': 2, 'dataset': 'Alpha Dataset', 'hardware': 'GPU A', 'baseline': 'Baseline *',
                   'conditionReferences': [{'sourceId': 'h', 'quote': hardware['text']}]}
    raw = {'summary': 'Alpha（GPU A，Baseline *）中，Ours 为200 FPS。', 'kind': 'reported',
           'references': [{'sourceId': 't', 'quote': BASE}, {'sourceId': 't', 'quote': OURS}],
           'measurements': [measurement]}
    return raw, {'t': table, 'h': hardware}


def check(raw, sources):
    checked = validate_claim(raw, list(sources.values()))
    validate_numeric_comparison(raw, checked, sources)
    return checked


def test_numeric_cell_keeps_its_dataset_hardware_baseline_and_same_paper_sources():
    raw, sources = fixture()
    checked = check(raw, sources)
    assert {ref['sourceId'] for ref in checked['references']} == {'t', 'h'}
    assert 'measurements' not in checked  # Existing public claim contract.


@pytest.mark.parametrize('change', ['missing', 'wrong_group', 'wrong_value', 'wrong_baseline', 'foreign_hardware', 'hidden_conditions', 'extra_number', 'unverified_table'])
def test_mixed_or_uncovered_experiment_numbers_are_rejected(change):
    raw, sources = fixture()
    if change == 'missing':
        raw.pop('measurements')
    elif change == 'wrong_group':
        raw['measurements'][0]['group'] = 1
    elif change == 'wrong_value':
        raw['measurements'][0]['value'] = '237'
    elif change == 'wrong_baseline':
        raw['measurements'][0]['baseline'] = 'Baseline'
    elif change == 'foreign_hardware':
        sources['h']['pdfId'] = 'B'
    elif change == 'hidden_conditions':
        raw['summary'] = 'Ours为200 FPS。'
    elif change == 'extra_number':
        raw['summary'] += '并为25 MB。'
    else:
        sources['t'].pop('_verifiedTable')
    with pytest.raises(ValueError):
        check(raw, sources)


@pytest.mark.parametrize('operation,metric,value,summary', [
    ('difference', 'FPS', '100', '差值100 FPS'),
    ('ratio', 'FPS', '2.00', '速度为2倍'),
    ('inverse_ratio', 'Size', '5', '存储压缩5倍')])
def test_derived_metrics_use_the_same_dataset_and_explicit_baseline(operation, metric, value, summary):
    raw, sources = fixture()
    raw['summary'] = 'Alpha（GPU A，Baseline *）：' + summary
    raw['kind'] = 'inference'
    raw['measurements'][0].update(operation=operation, metric=metric, value=value)
    check(raw, sources)


def test_false_compression_ratio_is_rejected():
    raw, sources = fixture()
    raw['summary'] = 'Alpha（GPU A，Baseline *）：存储压缩15倍。'
    raw['kind'] = 'inference'
    raw['measurements'][0].update(operation='inverse_ratio', metric='Size', value='15')
    with pytest.raises(ValueError, match='单元不一致'):
        check(raw, sources)


def test_derived_value_cannot_be_published_as_an_author_report():
    raw, sources = fixture()
    raw['summary'] = 'Alpha（GPU A，Baseline *）：速度为2倍。'
    raw['measurements'][0].update(operation='ratio', value='2')
    with pytest.raises(ValueError, match='须标为推断'):
        check(raw, sources)


def test_reported_prose_retains_support_with_one_continuous_result_context():
    raw, sources = fixture()
    quote = 'On Alpha Dataset, Ours reaches 200 FPS compared with Baseline *.'
    sources['p'] = {'sourceId': 'p', 'pdfId': 'A', 'text': quote}
    raw['references'] = [{'sourceId': 'p', 'quote': quote}]
    raw['measurements'][0].update(sourceId='p', quote=quote)
    check(raw, sources)
    raw['measurements'][0]['dataset'] = 'Beta Dataset'
    with pytest.raises(ValueError):
        check(raw, sources)


def test_table_packet_and_body_share_existing_budget_and_visible_complete_rows():
    raw, sources = fixture()
    source = sources['t']
    source['text'] = 'Original header. ' * 30 + BASE + '\n' + OURS
    body, packet = bounded_table_body(source, source['text'], 500)
    assert packet['rows'] == PACKET['rows']
    assert len(body) + len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) <= 500
    assert BASE in body and OURS in body and body in source['text']
    clipped, unavailable = bounded_table_body(source, source['text'], 30)
    assert unavailable is None


def test_critique_axis_receives_checked_columns_without_mutating_source_snapshots():
    from core.pdf_quality import _format_axis_prompt_block
    raw, sources = fixture()
    original = deepcopy(sources['t'])
    prompt = _format_axis_prompt_block({'label': '实验', 'key': 'experiments', 'evidence': [sources['t']]})
    assert 'PDF交叉核对的表格列' in prompt
    assert 'Alpha Dataset' in prompt and 'Beta Dataset' in prompt
    assert BASE in prompt and OURS in prompt
    assert sources['t'] == original
