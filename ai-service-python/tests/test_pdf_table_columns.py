from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from core.pdf_table_columns import drawing_runs, verify_table_columns, attach_verified_table_columns
from core.smart_chunker import chunk_sections
import json
from pathlib import Path
import pytest


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


def model_groups_fixture():
    def cell(text):
        return {'text': text, 'cols': 1, 'rows': 1}

    tei = [['Model', '', 'MetricA', 'MetricB', 'MetricC']]
    runs = []

    def draw(value, x, y):
        runs.append({'text': value, 'x': x, 'y': y, 'tokens': [{'text': value, 'x': x}]})

    for value, x in zip(('Model', 'MetricA', 'MetricB', 'MetricC'), (4, 70, 90, 110)):
        draw(value, x, 10)
    for name, start, offset in (('Model-A', 20, 0), ('Model-B', 57, 30)):
        for index, config in enumerate(('Baseline', '4bit (fake)', 'Grouped-4')):
            values = [str(offset + index * 3 + j) for j in (1, 2, 3)]
            tei.append([name if index == 1 else '', config, *values])
            y = start + index * 10
            if index == 1:
                draw(name, 4, y)
                draw('4bit (fake', 26, y)
                draw(')', 65, y)
            else:
                draw(config, 26, y)
            for value, x in zip(values, (73, 93, 113)):
                draw(value, x, y)
    rules = [(0, 120, y) for y in (15, 50, 90)]
    section = {'tableBounds': [0, 0, 120, 90], 'tableRows': [[cell(v) for v in row] for row in tei]}
    return section, runs, rules


def test_model_groups_require_drawn_boundaries_and_confirm_exact_values():
    from core.pdf_model_table import verify_model_groups

    section, runs, rules = model_groups_fixture()
    packet = verify_model_groups(section, runs, rules)
    assert packet['groups'] == [['', ['MetricA', 'MetricB', 'MetricC']]]
    assert packet['rows'][1] == [3, 'Model-A / 4bit (fake)', ['4', '5', '6']]
    assert packet['rows'][4] == [6, 'Model-B / 4bit (fake)', ['34', '35', '36']]
    assert verify_model_groups(section, runs, [rules[0], rules[-1]]) is None
    different_scope = deepcopy(section)
    different_scope['tableRows'][2][0]['text'] = 'Model-C'
    assert verify_model_groups(different_scope, runs, rules) is None
    different_value = deepcopy(section)
    different_value['tableRows'][1][2]['text'] = 'wrong value'
    retained = verify_model_groups(different_value, runs, rules)
    assert 2 not in {number for number, _, _ in retained['rows']}
    assert 5 in {number for number, _, _ in retained['rows']}


def fused_tables_fixture():
    section, runs, rules = model_groups_fixture()

    def cell(text):
        return {'text': text, 'cols': 1, 'rows': 1}

    def draw(text, x, y):
        runs.append({'text': text, 'x': x, 'y': y, 'tokens': [{'text': text, 'x': x}]})

    header, *ordinary = section['tableRows']
    header[1] = cell('Method')
    header[1]['cols'] = 2
    fused = []
    for group in (ordinary[:3], ordinary[3:]):
        name = group[1][0]['text']
        configurations = ' '.join(row[1]['text'] for row in group)
        reversed_values = ' '.join(value['text'] for row in reversed(group) for value in row[2:])
        fused.append([cell(name), cell(configurations + ' ' + reversed_values)])
    rows = [[cell('Method'), cell('Training')], [cell('Original'), cell('12')],
            [cell('Table 2: Independent results')], header, *fused, [cell('Figure tail')]]
    lines = ['Table caption: Table 1 : Setup',
             *(f'Table row {i}: ' + ' | '.join(c['text'] for c in row) for i, row in enumerate(rows, 1))]
    draw('Table 2: Independent results', 0, -10)
    draw('Method', 26, 10)
    section.update(tableId='tei-joined', section='Table 1 :', evidenceKind='table',
                   pageIndex=4, tableBounds=[0, -40, 120, 155], tableRows=rows,
                   tablePrefix='\n'.join(lines[:2]), content='\n'.join(lines))
    return section, runs, [(0, 120, 5), *rules]


def test_one_tei_zone_separates_the_physical_tables_without_promoting_figure_content():
    from core.pdf_table_columns import _split_fused_table

    section, runs, rules = fused_tables_fixture()
    earlier, recovered = _split_fused_table(section, runs, rules, [(2, '2')])
    assert earlier['tableId'] == 'tei-joined' and 'Independent results' not in earlier['content']
    assert recovered['tableId'] == 'pdf-page-5-table-2' and recovered['section'] == 'Table 2'
    assert recovered['tableVerifiedData']['rows'][0] == [2, 'Model-A / Baseline', ['1', '2', '3']]
    assert recovered['tableVerifiedData']['rows'][4] == [6, 'Model-B / 4bit (fake )', ['34', '35', '36']]
    assert 'Figure tail' not in recovered['content'] and 'Figure tail' not in earlier['content']


def test_fused_table_with_wrong_tuple_or_ambiguous_caption_stays_unverified():
    from core.pdf_table_columns import _split_fused_table

    section, runs, rules = fused_tables_fixture()
    changed = deepcopy(section)
    changed['tableRows'][4][1]['text'] += ' 999'
    assert _split_fused_table(changed, runs, rules, [(2, '2')]) is None
    duplicate = {'text': 'Table 2: Another label', 'x': 0, 'y': -27, 'tokens': []}
    assert _split_fused_table(section, [duplicate, *runs], rules, [(2, '2')]) is None


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


def main_table_fixture(name):
    return json.loads((Path(__file__).parent/'fixtures'/('dr_vq_'+name+'_main_geometry.json')).read_text(encoding='utf8'))


def test_real_mixed_dataset_groups_and_average_columns_are_verified_from_pdf():
    data=main_table_fixture('compact')
    assert verify_table_columns(data['section'],data['runs']) is None
    result=verify_table_columns(data['section'],data['runs'],mixed=True)
    assert result['groups']==[['Mip-NeRF360',['SSIM','PSNR','LPIPS']],
        ['Tanks&Temples',['SSIM','PSNR','LPIPS']],['Deep Blending',['SSIM','PSNR','LPIPS']],['Avg',['FPS','Mem']]]
    ours=next(r for r in result['rows'] if compact_label(r[1])=='CompGS4k')
    baseline=next(r for r in result['rows'] if compact_label(r[1])=='3DGS*')
    assert ours[2][:3]==['0.804','26.97','0.234'] and ours[2][-2:]==['142','51.6MB']
    assert baseline[2][-2:]==['142','607MB']


def compact_label(text):return ''.join(text.split())


def test_real_unequal_groups_keep_the_standalone_compression_ratio():
    data=main_table_fixture('compressed')
    assert verify_table_columns(data['section'],data['runs']) is None
    result=verify_table_columns(data['section'],data['runs'],mixed=True)
    assert result['groups']==[['3D Gaussian Splatting',['PSNR','SSIM','LPIPS','SIZE']],
        ['Ours',['PSNR','SSIM','LPIPS','SIZE']],['',['Compression Ratio']]]
    average=next(r for r in result['rows'] if r[1]=='average*')
    assert average[2]==['26.58','0.853','0.213','640.31','26.560','0.844','0.238','23.73','25.77']
    assert len(result['rows'])==5


@pytest.mark.parametrize('name',['compact','compressed'])
def test_numeric_change_cannot_be_verified_by_new_header_recovery(name):
    data=main_table_fixture(name);row=data['section']['tableRows'][-1]
    row[-1]['text']=row[-1]['text'].replace('54.6','54.7').replace('25.77','25.78')
    result=verify_table_columns(data['section'],data['runs'],mixed=True)
    assert not result or len(data['section']['tableRows']) not in {r[0] for r in result['rows']}


def test_wrong_tei_boundaries_are_recovered_only_as_actual_pdf_columns():
    section,runs=fixture();section['section']='Table 1'
    section['tableRows'][1][1]['text']='12';section['tableRows'][1][2]['text']='3MB'
    result=verify_table_columns(section,runs,mixed=True)
    recovered=next(r for r in result['rows'] if r[0]==2)
    assert recovered[2]==['1','23MB','4','56MB']  # Never publish damaged12/3MB.


def test_ambiguous_complete_physical_rows_are_not_selected_arbitrarily():
    section,runs=fixture();section['section']='Table 1'
    # A second physical baseline with exactly the same flattened value has no
    # unique correspondence to the TEI row. Other distinct rows may survive.
    duplicate=[{**r,'y':r['y']+15} for r in runs if r['y']==40]
    result=verify_table_columns(section,[*runs,*duplicate],mixed=True)
    assert not result or 2 not in {r[0] for r in result['rows']}


def test_unmatched_or_multilevel_irregular_headers_are_still_refused():
    data=main_table_fixture('compact');data['section']['tableRows'][0][2]['text']='Unrelated cohort'
    assert verify_table_columns(data['section'],data['runs'],mixed=True) is None
    section,runs,_=hierarchical_fixture();runs[0]['tokens'][0]['x']=300
    assert verify_table_columns(section,runs,mixed=True) is None


def test_single_level_unique_metric_columns_need_exact_physical_rows():
    def cell(text):return {'text':text,'rows':1,'cols':1}
    section={'section':'Table 3','tableBounds':[0,0,100,60],
        'tableRows':[[cell('Method'),cell('PSNR'),cell('SIZE')],[cell('Ours'),cell('25.0 40MB')]]}
    runs=[{'text':t,'x':x,'y':y,'tokens':[{'text':t,'x':x}]}
          for t,x,y in [('Method',1,10),('PSNR',30,10),('SIZE',60,10),('Ours',1,30),('25.0',31,30),('40MB',61,30)]]
    result=verify_table_columns(section,runs,mixed=True)
    assert result=={'groups':[['',['PSNR','SIZE']]],'rows':[[2,'Ours',['25.0','40MB']]]}


@pytest.mark.parametrize('name,page',[('compact',5),('compressed',6)])
def test_actual_caption_and_checked_cells_survive_attachment_and_chunking(name,page):
    data=main_table_fixture(name);section=deepcopy(data['section'])
    original_label=section['section'];reader=SimpleNamespace(pages=[{} for _ in range(page)])
    with patch('PyPDF2.PdfReader',return_value=reader),patch('core.pdf_table_columns.drawing_runs',return_value=[*data['runs'],*data['captionRuns']]):
        attach_verified_table_columns([section],'owned-original.pdf')
        first=deepcopy(section)
        attach_verified_table_columns([section],'owned-original.pdf')
        assert section==first
    assert section['section']=='Table 1' and section['tableId']==f'pdf-page-{page}-table-1'
    assert section['unverifiedTeiTableLabel']==original_label
    assert section['content'].startswith('Table caption: Table 1.') and section['tableColumnMappingVersion']==2
    chunks=chunk_sections([section]);retained=[c for c in chunks if c.get('tableVerifiedData')]
    assert retained and all(c['section']=='Table 1' for c in retained)
    for c in retained:
        for number,label,values in c['tableVerifiedData']['rows']:
            assert f'Table row {number}: '+' | '.join([label,*values]) in c['text'].splitlines()
    if name=='compact':assert 'averaged FPS and memory over all datasets' in section['content']
    else:assert 'Size is measured in Megabytes' in section['content']


def test_ambiguous_physical_captions_cannot_promote_newly_recovered_columns():
    data=main_table_fixture('compressed');section=deepcopy(data['section']);raw=deepcopy(section)
    duplicate=deepcopy(next(r for r in data['captionRuns'] if r['text'].startswith('Table')))
    duplicate['text']='Table2. Another possible caption.';duplicate['y']+=2
    reader=SimpleNamespace(pages=[{} for _ in range(6)])
    with patch('PyPDF2.PdfReader',return_value=reader),patch('core.pdf_table_columns.drawing_runs',return_value=[*data['runs'],*data['captionRuns'],duplicate]):
        attach_verified_table_columns([section],'owned-original.pdf')
    assert section==raw and 'tableVerifiedData' not in section
