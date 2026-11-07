from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from core.pdf_table_columns import drawing_runs, verify_table_columns, attach_verified_table_columns
from core.smart_chunker import chunk_sections
import json
from pathlib import Path


def fixture():
    def cell(text):
        return {'text': text, 'cols': 1, 'rows': 1}
    section = {'tableBounds': [0, 0, 120, 70], 'tableRows': [
        [cell('Method'), cell('Alpha Dataset FPS Size'), cell('Beta Dataset FPS Size')],
        [cell('Baseline *'), cell('1'), cell('23MB'), cell('4'), cell('56MB')],
        [cell('Ours'), cell('2'), cell('30MB'), cell('5'), cell('60MB')]]}
    runs = [{'text': label, 'x': x, 'y': 20, 'tokens': [{'text': label, 'x': x}]}
            for label, x in [('FPS', 30), ('Size', 50), ('FPS', 80), ('Size', 100)]]
    runs += [{'text': 'AlphaDataset', 'x': 40, 'y': 10, 'tokens': []},
             {'text': 'BetaDataset', 'x': 90, 'y': 10, 'tokens': []}]
    for y, values in [(40, ['Baseline *', '1', '23MB', '4', '56MB']),
                      (50, ['Ours', '2', '30MB', '5', '60MB'])]:
        runs += [{'text': value, 'x': x, 'y': y, 'tokens': [{'text': value, 'x': x}]}
                 for value, x in zip(values, [1, 31, 51, 81, 101])]
    return section, runs


def test_grouped_header_and_each_cell_are_cross_checked_with_pdf_positions():
    section, runs = fixture()
    checked = verify_table_columns(section, runs)
    assert checked['groups'] == [['Alpha Dataset', ['FPS', 'Size']], ['Beta Dataset', ['FPS', 'Size']]]
    assert checked['rows'] == [[2, 'Baseline *', ['1', '23MB', '4', '56MB']],
                               [3, 'Ours', ['2', '30MB', '5', '60MB']]]


def hierarchical_fixture():
    def cell(text):
        return {'text': text, 'cols': 1, 'rows': 1}
    names = ['PSNR', 'SSIM', 'LPIPS'] * 6
    xs = [50 + 20 * i for i in range(18)]
    values = [str(100 + i) for i in range(18)]
    section = {'tableBounds': [0, 0, 420, 70], 'tableRows': [
        [cell('Method'), cell('Alpha'), cell('Beta')],
        [cell(''), *map(cell, ['inner', 'outer', 'mean'] * 2)],
        [cell(''), cell(' '.join(names))],
        [cell('Ours'), cell(' '.join(values))]]}
    def run(texts, starts, y):
        return {'text': ''.join(texts), 'x': starts[0], 'y': y,
                'tokens': [{'text': t, 'x': x} for t, x in zip(texts, starts)]}
    runs = [run(['Alpha', 'Beta'], [70, 250], 10),
            run(['inner', 'outer', 'mean'] * 2, [70, 130, 190, 250, 310, 370], 20),
            run(names, xs, 30), run(['Ours'], [1], 50), run(values, xs, 50)]
    return section, runs, values


def test_merged_pdf_header_operations_preserve_parent_and_subgroup_identity():
    section, runs, values = hierarchical_fixture()
    packet = verify_table_columns(section, runs)
    assert packet['groups'] == [[f'{parent} / {child}', ['PSNR', 'SSIM', 'LPIPS']]
                               for parent in ['Alpha', 'Beta'] for child in ['inner', 'outer', 'mean']]
    assert packet['rows'] == [[4, 'Ours', values]]


def test_repeated_subheaders_without_corroborated_aligned_parents_stay_unverified():
    section, runs, _ = hierarchical_fixture()
    assert verify_table_columns(section, runs[1:]) is None
    wrong_position = deepcopy(runs)
    wrong_position[0]['tokens'][0]['x'] = 300
    assert verify_table_columns(section, wrong_position) is None
    missing_parent = deepcopy(section)
    missing_parent['tableRows'][0][1]['text'] = 'Invented cohort'
    assert verify_table_columns(missing_parent, runs) is None


def test_hierarchy_does_not_relax_numeric_cell_correspondence():
    section, runs, values = hierarchical_fixture()
    values[0], values[1] = values[1], values[0]
    section['tableRows'][-1][-1]['text'] = ' '.join(values)
    assert verify_table_columns(section, runs) is None


def test_real_three_dataset_table_with_math_headers_and_merged_tei_cells():
    fixture_path = Path(__file__).parent / 'fixtures/dr_table1_geometry.json'
    data = json.loads(fixture_path.read_text(encoding='utf-8'))
    result = verify_table_columns(data['section'], data['runs'])
    assert [g[0] for g in result['groups']] == ['Mip-NeRF360', 'Tanks&Temples', 'Deep Blending']
    assert all(g[1] == ['SSIM', 'PSNR', 'LPIPS', 'Train', 'FPS', 'Mem'] for g in result['groups'])
    row = next(row for row in result['rows'] if row[1] == 'Ours-30K')
    assert row[2] == ['0.815', '27.21', '0.214', '41m33s', '134', '734MB',
                      '0.841', '23.14', '0.183', '26m54s', '154', '411MB',
                      '0.903', '29.41', '0.243', '36m2s', '137', '676MB']
    # Same concatenated digits with a different boundary must not be accepted.
    bad = deepcopy(data['section'])
    bad['tableRows'][7][4]['text'] = '41m33s 13 4734MB'
    assert 'Ours-30K' not in {r[1] for r in verify_table_columns(bad, data['runs'])['rows']}


def test_dataset_label_must_be_corroborated_in_tei_and_pdf():
    section, runs = fixture()
    runs[4]['text'] = 'InventedDataset'
    assert verify_table_columns(section, runs) is None


def test_long_caption_retains_only_complete_geometry_checked_rows():
    prefix = 'Table caption: ' + 'Long explanatory caption. ' * 35
    row = 'Table row 2: Ours | 200'
    section = {'section': 'Table 1', 'evidenceKind': 'table', 'tablePrefix': prefix,
               'content': prefix + '\n' + row,
               'tableVerifiedData': {'groups': [['Example', ['FPS']]], 'rows': [[2, 'Ours', ['200']]]}}
    chunks = chunk_sections([section])
    retained = [c for c in chunks if c.get('tableVerifiedData')]
    assert retained and all(row in c['text'].splitlines() for c in retained)
    section['content'] = prefix + '\n' + row + 'invalid'
    assert all('tableVerifiedData' not in c for c in chunk_sections([section]))


def test_equal_concatenation_does_not_verify_a_different_cell_split():
    section, runs = fixture()
    section['tableRows'][1][1]['text'] = '12'
    section['tableRows'][1][2]['text'] = '3MB'
    assert [row[0] for row in verify_table_columns(section, runs)['rows']] == [3]


def test_merged_or_incomplete_rows_are_not_marked_verified():
    section, runs = fixture()
    section['tableRows'][1][1]['cols'] = 2
    section['tableRows'][2].pop()
    assert verify_table_columns(section, runs) is None


def test_misaligned_group_heading_and_unknown_font_widths_leave_rows_unverified():
    section, runs = fixture()
    runs[4]['x'] = 85
    assert verify_table_columns(section, runs) is None
    section, runs = fixture()
    for run in runs:
        run['tokens'] = None
    assert verify_table_columns(section, runs) is None


def test_pdf_drawing_tokens_keep_kerning_coordinates_font_widths_and_star_mapping():
    class Page:
        mediabox = SimpleNamespace(height=100)
        def __getitem__(self, key):
            return {'/Font': {'/F': {}}}
        def extract_text(self, visitor_operand_before):
            cm, tm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 10, 80]
            visitor_operand_before(b'Tf', ['/F', 10], cm, tm)
            visitor_operand_before(b'TJ', [[b'12', -1000, b'3MB']], cm, tm)
            visitor_operand_before(b'TJ', [[b'\x03']], cm, tm)
    font = {'/Widths': [500] * 256, '/FirstChar': 0}
    with patch('PyPDF2._cmap.build_char_map', return_value=('Type1', 100, 'latin-1', {'\x03': '∗'}, font)):
        runs = drawing_runs(Page())
    assert runs[0]['tokens'] == [{'text': '12', 'x': 10}, {'text': '3MB', 'x': 30}]
    assert runs[1]['text'] == '∗' and runs[1]['tokens'][0]['text'] == '∗'
    assert runs[1]['tokens'][0]['x'] == 45  # Consecutive TJ continues after 3MB.


def test_text_position_reset_clears_advance_and_unsupported_font_cannot_verify_next_cells():
    class Page:
        mediabox = SimpleNamespace(height=100)
        def __getitem__(self, key):
            return {'/Font': {'/F': {}, '/Unknown': {}}}
        def extract_text(self, visitor_operand_before):
            cm, tm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 10, 80]
            visitor_operand_before(b'Tf', ['/F', 10], cm, tm)
            visitor_operand_before(b'Tj', [b'123'], cm, tm)
            visitor_operand_before(b'Tm', tm, cm, tm)
            visitor_operand_before(b'Tj', [b'4'], cm, tm)
            visitor_operand_before(b'Tf', ['/Unknown', 10], cm, tm)
            visitor_operand_before(b'Tj', [b'?'], cm, tm)
            visitor_operand_before(b'Tf', ['/F', 10], cm, tm)
            visitor_operand_before(b'Tj', [b'5'], cm, tm)
            visitor_operand_before(b'Td', [0, -10], cm, tm)
            visitor_operand_before(b'Tj', [b'6'], cm, tm)
    def font(name, *args):
        return ('Type1', 100, 'latin-1', {}, {'/Widths': [500]*256, '/FirstChar': 0} if name == '/F' else {})
    with patch('PyPDF2._cmap.build_char_map', side_effect=font):
        runs = drawing_runs(Page())
    assert runs[1]['tokens'] == [{'text': '4', 'x': 10}]
    assert runs[2]['tokens'] is None and runs[3]['tokens'] is None
    assert runs[4]['tokens'] == [{'text': '6', 'x': 10}]


def test_unreadable_pdf_leaves_original_sections_available():
    sections = [{'section': 'Original', 'content': 'Original body'}]
    with patch('PyPDF2.PdfReader', side_effect=ValueError('unsupported PDF')):
        assert attach_verified_table_columns(sections, 'unavailable.pdf') == sections


def test_verified_table_metadata_only_follows_the_rows_visible_in_each_chunk():
    prefix = 'Table caption: Table 1\nTable row 1: Method | FPS'
    row = 'Table row 2: Ours | 200'
    section = {'section': 'Table 1', 'evidenceKind': 'table', 'tablePrefix': prefix,
               'content': prefix + '\n' + row,
               'tableVerifiedData': {'groups': [['Alpha Dataset', ['FPS']]],
                                     'rows': [[2, 'Ours', ['200']], [3, 'Absent', ['100']]]}}
    chunks = chunk_sections([section])
    assert chunks[0]['tableVerifiedData']['rows'] == [[2, 'Ours', ['200']]]
    broken = deepcopy(section)
    broken['content'] += 'v' * 3000
    assert all('tableVerifiedData' not in chunk for chunk in chunk_sections([broken]))
