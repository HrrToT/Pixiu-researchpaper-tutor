from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.pdf_benchmark_columns import verify_two_tier_columns


def benchmark():
    def cell(text, cols=1):
        return {'text': text, 'rows': 1, 'cols': cols}

    def run(x, y, text):
        return {'x': x, 'y': y, 'text': text, 'tokens': [{'x': x, 'text': text}]}

    groups = [['Trainable', ['Parameters']], ['Dataset A', ['Accuracy (%)']], ['Dataset B', ['R1/R2/RL']]]
    values = [['Full tune', '31.5M', '72.0', '40.1/25.3/38.5'],
              ['Low rank', '2.2M', '73.4', '41.2/25.9/39.6'],
              ['Low rank', '5.0M', '74.0', '42.7/26.2/40.4']]
    rows = [[cell('Method'), cell('Trainable Dataset A Parameters Accuracy (%)', 2), cell('Dataset B R1/R2/RL')],
            *[[cell(text) for text in row] for row in values]]
    drawing = [run(40, 30, 'Method')]
    for col, (group, metrics) in enumerate(groups, 2):
        drawing.extend([run(80 * col, 24, group), run(80 * col, 36, metrics[0])])
    for i, row in enumerate(values):
        drawing.extend(run(x, 50 + i * 13, text) for x, text in zip((40, 164, 244, 324), row, strict=True))
    from_document = {'tableBounds': [40, 22, 335, 58], 'tableRows': rows, 'tableId': 'tab_3',
                     'section': 'raw caption number', 'pageIndex': 0, 'evidenceKind': 'table',
                     'content': 'Table caption: raw caption number\n'
                     + '\n'.join(f'Table row {i}: ' + ' | '.join(row) for i, row in enumerate(values, 2))}
    return from_document, drawing, {'groups': groups, 'rows': [[i,row[0],row[1:]] for i,row in enumerate(values,2)]}


def test_reconstructs_columns_from_two_physical_header_lines_and_exact_rows():
    section, drawing, expected = benchmark()
    baseline = deepcopy((section, drawing))
    assert verify_two_tier_columns(section, drawing) == expected
    assert (section, drawing) == baseline


@pytest.mark.parametrize('change', ['shifted_header', 'unknown_header', 'duplicate_heading', 'collapsed_geometry'])
def test_two_tier_decoder_rejects_ambiguous_column_layout(change):
    section, drawing, _ = benchmark()
    group = next(run for run in drawing if run['text'] == 'Dataset A')
    if change == 'shifted_header':
        group['tokens'][0]['x'] = 163
    elif change == 'unknown_header':
        group['tokens'] = None
    elif change == 'duplicate_heading':
        group['text'] = group['tokens'][0]['text'] = 'Dataset B'
    else:
        for run in drawing:
            if run['x'] == 244:
                run['tokens'][0]['x'] = 170
    assert verify_two_tier_columns(section, drawing) is None


def test_row_numbers_remain_bound_when_one_tei_result_is_corrupted():
    section, drawing, expected = benchmark()
    row = section['tableRows'][1]
    row[1]['text'], row[2]['text'] = row[2]['text'], row[1]['text']
    assert verify_two_tier_columns(section, drawing) == {**expected, 'rows': expected['rows'][1:]}


@pytest.mark.parametrize('additional_caption', [False, True])
def test_attaches_two_tier_packet_only_when_physical_caption_is_unique(monkeypatch, additional_caption):
    import PyPDF2
    from core import pdf_table_columns
    from services.deep_research.table_evidence import visible_table_packet

    section, drawing, expected = benchmark()
    drawing.append({'text':'Table 3: Benchmarks', 'x':10, 'y':98,
                    'tokens':[{'text':'Table 3: Benchmarks', 'x':10}]})
    if additional_caption:
        drawing.append({'text':'Table 4: Other results', 'x':30, 'y':102,
                        'tokens':[{'text':'Table 4: Other results', 'x':30}]})
    monkeypatch.setattr(PyPDF2, 'PdfReader', lambda _: SimpleNamespace(pages=[{}]))
    monkeypatch.setattr(pdf_table_columns, 'drawing_runs', lambda _: drawing)
    verified, = pdf_table_columns.attach_verified_table_columns([section], 'fixture.pdf')
    if additional_caption:
        assert 'tableVerifiedData' not in verified
    else:
        assert verified['tableId'] == 'pdf-page-1-table-3'
        assert visible_table_packet(verified['tableVerifiedData'],verified['content']) == expected
