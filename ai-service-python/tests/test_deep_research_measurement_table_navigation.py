"""Requested table cells survive bounded reading/extraction/premise navigation."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.measurement_table_navigation import score
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.reading_roles import premise_bundles
from services.deep_research.synthesis_evidence import order_premises
from services.deep_research.graph import make_read_node
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.verification import make_evidence


QUESTION = 'Report storage, quality, and rendering-speed results each paper states, with the conditions under which they were obtained.'


def source(work, *, metric='PSNR', dataset='Dataset-R2', version=None):
    packet = {'groups': [[dataset, [metric]]], 'rows': [[1, 'Ours', ['31.25']]]}
    return {'sourceId': 'table-'+work, 'workId': work, 'ownerMaterialId': work,
            'versionId': version or work+'-v1', 'contentHash': 'hash-'+work,
            'title': 'Study '+work, 'accessLevel': 'fulltext',
            'text': 'Table 1: Quantitative comparison.\nTable row 1: Ours | 31.25',
            'location': {'section': 'Results', 'page': 1}, 'tableData': packet, 'obligationIds': ['o']}


def inputs():
    obs = {'o': {'obligationId': 'o', 'question': QUESTION, 'requiredSources': ['a-v1', 'b-v1'],
        'completionCriteria': [{'criterionId': 'measurements', 'requirement': QUESTION}]}}
    tables = [source('a'), source('b')]
    prose = [{**source(work), 'sourceId': 'prose-'+work, 'tableData': None,
        'text': 'We report storage quality and rendering-speed performance results with conditions.'}
        for work in ['a', 'b']]
    return obs, [*prose, *tables]


@pytest.mark.parametrize('query,metric', [('质量', 'PSNR'), ('画质', 'SSIM'), ('quality', 'LPIPS'),
    ('rendering-speed', 'FPS'), ('渲染速度', 'FPS'), ('latency', 'LATENCY'),
    ('存储', 'Mem'), ('memory', 'SIZE'), ('compression ratio', 'Compression Ratio')])
def test_literal_metric_domains_find_visible_numeric_rows(query, metric):
    assert score(source('a', metric=metric), {'role': 'result', 'query': query}) > 0


@pytest.mark.parametrize('change', ['missing_row', 'different_values', 'metadata_only', 'abstract',
                                  'nonnumeric', 'unrequested_metric', 'wrong_role', 'wrong_benchmark'])
def test_hints_cannot_replace_visible_cells_scope_or_requested_metric(change):
    row = source('a'); request = {'role': 'result', 'query': 'PSNR on Dataset-R2'}
    if change == 'missing_row': row['text'] = 'A caption without its literal row.'
    elif change == 'different_values': row['text'] = row['text'].replace('31.25', '99.0')
    elif change == 'metadata_only': row['text'] = ''
    elif change == 'abstract': row['accessLevel'] = 'abstract'
    elif change == 'nonnumeric':
        row['tableData']['rows'][0][2] = ['unknown']; row['text'] = row['text'].replace('31.25', 'unknown')
    elif change == 'unrequested_metric': row = source('a', metric='SSIM')
    elif change == 'wrong_role': request['role'] = 'procedure'
    elif change == 'wrong_benchmark': row = source('a', dataset='Dataset-Z3')
    assert score(row, request) == 0


def test_same_cap_two_papers_and_legacy_order_are_preserved_without_source_mutation():
    obs, rows = inputs(); before = deepcopy(rows)
    options = {'priority_version': 10, 'substantive': True, 'mixed_script_terms': True}
    old = select_read_sources(rows, obs, 2, **options)
    current = select_read_sources(rows, obs, 2, **options, measurement_tables=True)
    assert [s['sourceId'] for s in old] == ['prose-a', 'prose-b']
    assert {s['sourceId'] for s in current} == {'table-a', 'table-b'}
    assert all(any(item is original for original in rows) for item in current)
    assert rows == before and len(current) == 2


def test_requested_benchmark_is_not_displaced_by_wrong_table_or_incidental_prose():
    obs, rows = inputs(); obs['o']['completionCriteria'][0]['requirement'] = 'Compare PSNR on Dataset-R2'
    wrong = source('a', dataset='Dataset-Z3'); wrong['sourceId'] = 'wrong-a'
    wrong['text'] += '\nElsewhere we discuss Dataset-R2.'
    selected = select_read_sources([wrong, *rows], obs, 2, priority_version=10,
                                   substantive=True, measurement_tables=True)
    assert {s['sourceId'] for s in selected} == {'table-a', 'table-b'}


def test_required_version_and_index_owner_are_not_overridden_by_table_priority():
    obs, rows = inputs(); foreign = source('a', version='a-v2'); foreign['sourceId'] = 'new-version'
    spoof = source('a'); spoof['sourceId'] = 'b-v'+'a'*16+'-chunk-1'
    selected = select_read_sources([foreign, spoof, *rows], obs, 2, priority_version=10,
                                   substantive=True, measurement_tables=True)
    assert {s['sourceId'] for s in selected} == {'table-a', 'table-b'}


def test_read_node_v8_rechecks_scope_and_does_not_upgrade_v7():
    obs, rows = inputs()
    def run(version):
        record = {'readingPriorityContractVersion': version, 'state': {'sources': rows,
            'plan': [{'obligations': list(obs.values())}], 'outputKind': 'paper_comparison'}, 'budget': {}}
        def update(rid, fn, **kwargs):
            nonlocal record
            record = fn(deepcopy(record)); return deepcopy(record)
        reads = []
        def read(rid, sid): reads.append(sid); return {}
        make_read_node(read, lambda rid, owner: owner == 'a', update)(
            {'run_id': 'r', 'source_ids': [s['sourceId'] for s in rows]})
        assert record['state']['sources'] == rows
        assert all(not sid.endswith('-b') for sid in reads)
        return reads
    assert run(8)[0] == 'table-a'
    assert run(7)[0] == 'prose-a'


def test_model_free_graph_read_extract_and_premise_stages_keep_original_table_cells():
    obs, rows = inputs()
    record = {'runId': 'r', 'readingPriorityContractVersion': 8,
        'adaptiveExtractionContractVersion': 3, 'state': {'sources': rows, 'evidence': [],
        'plan': [{'itemId': 'comparison', 'obligations': list(obs.values())}], 'outputKind': 'paper_comparison'},
        'budget': {'profile': 'standard'}}
    def update(rid, fn, **kwargs):
        nonlocal record
        record = fn(deepcopy(record)); return deepcopy(record)
    def read(rid, sid):
        row = next(s for s in rows if s['sourceId'] == sid)
        return {'accessLevel': 'fulltext', 'pages': [{'page': 1, 'text': row['text']}]}
    scope = lambda *args: True
    make_read_node(read, scope, update)({'run_id': 'r', 'source_ids': [s['sourceId'] for s in rows]})
    invoke = Mock(side_effect=AssertionError('No model call for literal extraction'))
    make_batched_extract_node(invoke, make_evidence, scope, update)({'run_id': 'r'})
    evidence = record['state']['evidence']
    table_rows = [e for e in evidence if e.get('tableData')]
    assert {e['sourceWorkId'] for e in table_rows} == {'a', 'b'}
    assert all(e['quote'] in e['sourceContext'] and e['verification']['semantic'] == 'unchecked' for e in table_rows)
    selected, bundles = order_premises(evidence, record['state']['plan'], limit=2,
        request_roles=True, mixed_script_terms=True, measurement_tables=True)
    assert {e['sourceWorkId'] for e in selected} == {'a', 'b'}
    assert all(e.get('tableData') and e['tableData']['rows'][0][2] == ['31.25'] for e in selected)
    assert {b['source'] for b in bundles} == {'a-v1', 'b-v1'}
    invoke.assert_not_called()


def test_unchecked_or_foreign_literal_evidence_never_enters_navigation_bundles():
    obs, rows = inputs(); row = rows[-1]
    evidence = {'evidenceId': 'e', 'sourceWorkId': row['workId'], 'sourceVersionId': row['versionId'],
        'quote': row['text'], 'sourceContext': row['text'], 'tableData': row['tableData'],
        'location': row['location'], 'accessLevel': 'fulltext', 'verification': {'literal': 'unchecked'}}
    assert premise_bundles([evidence], obs, measurement_tables=True) == ([], [])
    evidence['verification']['literal'] = 'passed'; evidence['sourceVersionId'] = 'b-v2'
    assert premise_bundles([evidence], obs, measurement_tables=True) == ([], [])
