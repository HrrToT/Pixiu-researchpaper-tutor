from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from core.pdf_table_columns import drawing_runs, verify_table_columns, attach_verified_table_columns
from core.smart_chunker import chunk_sections


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
