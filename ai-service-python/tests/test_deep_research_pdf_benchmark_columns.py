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


@pytest.mark.parametrize('mode', ['omitted', 'merged', 'shifted', 'conflicting_row', 'ambiguous_caption'])
def test_ruled_percentages_preserve_column_owner_without_tei_layout(monkeypatch, mode):
    import PyPDF2
    from core import pdf_model_table, pdf_table_columns
    from services.deep_research.table_evidence import visible_table_packet

    def run(x, y, text):
        return {'x': x, 'y': y, 'text': text, 'tokens': [{'x': x, 'text': text}]}

    positions = [111, 150, 190, 230, 260, 305, 335]
    rows = [['Model-A', '10.00', '50.00', '22.00', '15.00', '45.00', '33.00'],
            ['Model-B', '8.00', '35.00', '19.00', '11.00', '30.00', '26.00']]
    drawing = [run(230, 20, 'Activation'), run(305, 20, 'Weight'),
               run(111, 27, 'PPL'), run(150, 27, 'FP16'), run(190, 27, 'RTN'),
               run(190, 38, 'INT3'), run(230, 38, '0.1%'), run(260, 38, '1%'),
               run(305, 38, '0.1%'), run(335, 38, '1%'), run(102, 100, 'Table 1. Results')]
    drawing.extend(run(x, y, text) for y, row in zip((58, 72), rows, strict=True)
                   for x, text in zip(positions, row, strict=True))
    rules = [(100, 355, y) for y in (10, 45, 85)] + [(230, 278, 27), (305, 350, 27)]
    plain = ['0.1% 1% 0.1% 1%', *(' '.join(row) for row in rows)]
    sections = []
    if mode == 'merged':
        sections.append({'id': 'table-raw', 'tableId': 'raw', 'section': 'Table 1 .', 'pageIndex': 0,
                         'evidenceKind': 'table', 'content': 'Merged raw tables',
                         'tableBounds': [100, 13, 255, 150], 'tableRows': []})
    elif mode == 'shifted':
        drawing[7]['tokens'][0]['x'] = 304
    elif mode == 'conflicting_row':
        plain[1] = plain[1].replace('15.00', '51.00')
    elif mode == 'ambiguous_caption':
        drawing.append(run(103, 103, 'Table 2. Other Results'))

    class Page(dict):
        def extract_text(self):
            return '\n'.join(plain)

    monkeypatch.setattr(PyPDF2, 'PdfReader', lambda _: SimpleNamespace(pages=[Page()]))
    monkeypatch.setattr(pdf_table_columns, 'drawing_runs', lambda _: drawing)
    monkeypatch.setattr(pdf_model_table, 'horizontal_rules', lambda _: rules)
    verified = pdf_table_columns.attach_verified_table_columns(sections, 'fixture.pdf')
    if mode in ('shifted', 'conflicting_row', 'ambiguous_caption'):
        assert not verified
        return
    table, = verified
    assert (table['tableId'], table['page']) == ('pdf-page-1-table-1', 1)
    assert visible_table_packet(table['tableVerifiedData'], table['content']) == {
        'groups': [['', ['FP16', 'RTN INT3']], ['Activation', ['0.1%', '1%']], ['Weight', ['0.1%', '1%']]],
        'rows': [[i, label, cells] for i, (label, *cells) in enumerate(rows, 2)],
    }
