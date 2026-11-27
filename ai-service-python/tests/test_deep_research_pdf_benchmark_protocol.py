from copy import deepcopy

import pytest

from services.deep_research.pdf_benchmark_protocol import include_protocol, readiness_source_ids


PROSE = ('3. Experiments\n'
         '3.1 BenchMark-X Correspondence\n'
         'We evaluate on the local pairs. We use mutual matching and estimate the geometric transform. '
         'The success rates are given in Table 4.\n'
         '3.2 Other Results\n'
         'We evaluate on a different named collection. We use two GPUs.\n')


def example():
    rows = [
        {'sourceId': 'first'},
        {'sourceId': 'table', 'pdfId': 'work', 'contentHash': 'hash', 'versionId': 'edition',
         'text': 'Table caption: Table 4. BenchMark-X Correspondence.',
         'tableData': {'groups': [['Success', ['ϵ=3']]]},
         'location': {'page': 2, 'section': 'Table 4', 'thresholdColumnsVerified': True}},
        {'sourceId': 'other'},
    ]
    pages = [{'page': 2, 'text': PROSE}]
    material = {'materialId': 'work', 'contentHash': 'hash', 'versionId': 'edition'}
    return rows, pages, material


def test_retains_exact_subsection_in_existing_retrieval_slot():
    rows, pages, material = example()
    best, table, protocol = include_protocol(rows, pages, material, {'benchmark-x'}, 3)
    location = protocol['location']
    assert (best, table) == tuple(rows[:2])
    assert location['benchmarkProtocolFor'] == 'table' and location['page'] == 2
    assert PROSE[location['offset']:location['offset'] + len(protocol['text'])] == protocol['text']
    assert 'mutual matching' in protocol['text'] and 'two GPUs' not in protocol['text']

    normalized = [{**row, 'ownerMaterialId': 'work', 'workId': 'work'} for row in (table, protocol)]
    source_ids = {'table', protocol['sourceId']}
    assert readiness_source_ids(normalized, {'benchmark-x'}, source_ids) == source_ids
    assert readiness_source_ids(normalized, {'benchmark-x'}, {'table'}) == set()
    altered = deepcopy(normalized)
    altered[-1]['versionId'] = 'other-edition'
    assert readiness_source_ids(altered, {'benchmark-x'}, source_ids) == set()


@pytest.mark.parametrize('fault', ['wrong-page', 'wrong-reference', 'wrong-heading', 'wrong-owner'])
def test_requires_literal_same_page_table_identity(fault):
    rows, pages, material = example()
    if fault == 'wrong-page':
        rows[1]['location']['page'] += 1
    elif fault == 'wrong-reference':
        pages[0]['text'] = PROSE.replace('in Table 4', 'in Table 5')
    elif fault == 'wrong-heading':
        pages[0]['text'] = PROSE.replace('BenchMark-X', 'BenchMark-Y')
    else:
        rows[1]['pdfId'] = 'another-work'
    assert include_protocol(rows, pages, material, {'benchmark-x'}, 3) == rows
