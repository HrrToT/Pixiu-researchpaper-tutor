from copy import deepcopy

import pytest

from services.deep_research.pdf_benchmark_protocol import include_protocol, readiness_source_ids, synthesis_metric_bundles


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


@pytest.mark.parametrize('fault', [None, 'missing-reference', 'other-metric', 'other-symbol'])
def test_cited_appendix_adds_original_definition_only_for_the_tables_metric(fault):
    rows, pages, material = example()
    pages[0]['text'] = ('3. Experiments\nFor more details on our evaluation metrics, see Appendix A.\n'
                        + PROSE.split('\n', 1)[1])
    pages.append({'page': 5, 'text': 'A. Evaluation Metrics\n'
                  'Success. We compare projected locations against the registered target coordinates. '
                  'We use a threshold ε to decide whether the observed error is correct. '
                  'The scores represent the fraction of correct estimates.\n'
                  'B. Other Experiments\nOther material.\n'})
    if fault == 'missing-reference':
        pages[0]['text'] = pages[0]['text'].replace(' see Appendix A.', ' measure the result.')
    elif fault == 'other-metric':
        pages[1]['text'] = pages[1]['text'].replace('Success.', 'Accuracy.')
    elif fault == 'other-symbol':
        pages[1]['text'] = pages[1]['text'].replace('threshold ε', 'threshold τ')
    result = include_protocol(rows, pages, material, {'benchmark-x'}, 4, include_metric_definition=True)
    definition = [row for row in result if row.get('location', {}).get('benchmarkMetricDefinition')]
    if fault:
        assert definition == []
        return
    metric, = definition
    loc = metric['location']
    assert loc['benchmarkProtocolFor'] == 'table' and loc['page'] == 5
    assert pages[1]['text'][loc['offset']:loc['offset'] + len(metric['text'])] == metric['text']
    assert 'Other material' not in metric['text']


def test_synthesis_metric_group_cannot_cross_source_version():
    rows, _, _ = example()
    table = rows[1]
    base = {'ownerMaterialId': 'work', 'sourceWorkId': 'work', 'sourceVersionId': 'v1', 'contentHash': 'hash',
            'verification': {'literal': 'passed'}}
    evidence = [
        dict(table, **base, evidenceId='table-ev'),
        dict(base, evidenceId='protocol-ev', location={'benchmarkProtocolFor': 'table'}),
        dict(base, evidenceId='metric-ev', location={'benchmarkProtocolFor': 'table', 'benchmarkMetricDefinition': 'Success'}),
    ]
    aliases = {'E1': 'table-ev', 'E2': 'protocol-ev', 'E3': 'metric-ev'}
    stage = [{'evidenceId': e} for e in aliases]
    assert synthesis_metric_bundles(evidence, stage, aliases) == [('E1', 'E2', 'E3')]
    evidence[-1]['sourceVersionId'] = 'v2'
    assert synthesis_metric_bundles(evidence, stage, aliases) == []
