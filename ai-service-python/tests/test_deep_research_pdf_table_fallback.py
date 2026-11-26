from core.pdf_repeated_metric_tables import verified_metric_tables
from services.deep_research.table_note_index import matched_protocols


def draw(text, x, y):
    return {'text': text, 'x': x, 'y': y, 'tokens': [{'text': text, 'x': x}]}


def test_pdf_only_table_requires_same_group_headers_and_matching_drawn_rows(monkeypatch):
    runs = [draw('Dataset A', 185, 54), draw('Dataset B', 285, 54),
            draw('FPS', 170, 61), draw('Size', 220, 61), draw('FPS', 270, 61), draw('Size', 320, 61),
            draw('Base', 132, 69), draw('100', 170, 69), draw('50MB', 220, 69),
            draw('150', 270, 69), draw('60MB', 320, 69),
            draw('Ours', 132, 76), draw('200', 170, 76), draw('20MB', 220, 76),
            draw('230', 270, 76), draw('30MB', 320, 76),
            draw('Table 1: Comparison.', 132, 94)]
    monkeypatch.setattr('core.pdf_repeated_metric_tables.drawing_runs', lambda _: runs)
    monkeypatch.setattr('core.pdf_model_table.horizontal_rules', lambda _: [(130, 355, 45), (130, 355, 85)])
    text = ('Methods Dataset A Dataset B\nFPS↑ Size↓ FPS↑ Size↓\n'
            'Base 100 50MB 150 60MB\nOurs 200 20MB 230 30MB\nTable 1: Comparison.')
    table, = verified_metric_tables({}, text)
    assert table['number'] == '1'
    assert table['tableData'] == {
        'groups': [['Dataset A', ['FPS', 'Size']], ['Dataset B', ['FPS', 'Size']]],
        'rows': [[2, 'Base', ['100', '50MB', '150', '60MB']], [3, 'Ours', ['200', '20MB', '230', '30MB']]],
    }
    assert table['metricDirections'] == ('↑', '↓', '↑', '↓')
    assert not verified_metric_tables({}, text.replace('200 20MB', '20MB 200'))
    assert not verified_metric_tables({'/Rotate': 90}, text)


def test_directional_pdf_headers_retain_original_rows_and_remain_searchable():
    from services.deep_research.local_sources import LocalTaskRetriever, _include_metric_tables

    table = {'number': '1', 'caption': 'Table 1: Measurements.',
             'tableData': {'groups': [['Data', ['FPS', 'PSNR']]],
                           'rows': [[2, 'Reference', ['10', '27']], [3, 'Ours', ['20', '26']]]},
             'metricDirections': ('↑', '↑')}
    material = {'contentHash': 'hash', 'versionId': 'version'}
    page = {'page': 1, 'text': '', 'verifiedTables': [table]}
    old, = LocalTaskRetriever._pdf_passages('paper', material, [page], record={})
    revised, = LocalTaskRetriever._pdf_passages('paper', material, [page],
        record={'comparisonBenchmarkSpeedScopeContractVersion': 7})
    assert old['tableData'] == table['tableData']
    assert revised['tableData']['groups'] == [['Data', ['FPS↑', 'PSNR↑']]]
    assert revised['tableData']['rows'] == old['tableData']['rows']
    assert _include_metric_tables([], [revised], 'PSNR', {'PSNR'}, 2, marked_headers=True) == [revised]


def test_multiple_markers_require_one_visible_baseline_twin_and_one_explicit_note():
    labels = ['Base', 'Base∗', 'Another∗', 'Ours']
    rows = [[index, label, [str(index)]] for index, label in enumerate(labels, 2)]
    table = {
        'evidenceId': 'table', 'location': {'tableColumnMappingUnverified': False},
        'quote': '\n'.join(f'Table row {n}: {label} | {values[0]}' for n, label, values in rows),
        'tableData': {'groups': [['Dataset', ['FPS']]], 'rows': rows},
    }
    note = {'evidenceId': 'note',
            'quote': 'We re-trained Base and Another using original code on our GPU, with results marked by ∗.'}
    owners = {'table': ('paper', 'v1'), 'note': ('paper', 'v1')}
    assert matched_protocols([table, note], owners) == {'table': {'rowNumber': 3, 'noteEvidenceId': 'note'}}
    assert not matched_protocols([{**table, 'location': {}}, note], owners)
    assert not matched_protocols([table, {**note, 'quote': note['quote'].replace('Base and ', '')}], owners)
    assert not matched_protocols([table, note], {**owners, 'note': ('paper', 'v2')})
