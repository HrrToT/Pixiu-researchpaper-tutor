import copy
import json
from unittest.mock import patch

import pytest

from services.grounded_comparison import synthesize_comparison, grounded_source_map
from services.operation_control import OperationCancelled, cancellation_scope

SOURCES = [{'sourceId': 'a-1', 'pdfId': 'A', 'text': 'We maximize the radar SINR subject to communication constraints.'},
           {'sourceId': 'b-1', 'pdfId': 'B', 'text': 'We maximize the mutual information under a minimum communication rate.'}]


def payload():
    cells = [{'paperId': paper, 'summary': text, 'kind': 'reported',
              'references': [{'sourceId': source['sourceId'], 'quote': source['text']}]}
             for paper, text, source in zip(['A', 'B'], ['雷达SINR', '互信息'], SOURCES)]
    return {'claims': [{'summary': '优化目标分别为雷达SINR与互信息。', 'kind': 'reported', 'paperIds': ['A', 'B'],
                        'references': [cell['references'][0] for cell in cells]}],
            'dimensions': [{'label': '优化目标', 'cells': cells}], 'limitations': ['实验条件不同，不能直接排名。']}


def call(value):
    with patch('services.socratic_service._call_guarded_llm', return_value=json.dumps(value)):
        return synthesize_comparison('比较优化目标', SOURCES, ['A', 'B'])


def test_each_paper_and_cross_paper_claim_have_literal_quotes():
    result = call(payload())
    assert '| 优化目标 |' in result['message']
    assert '[1]' in result['message'] and '[2]' in result['message']
    assert '<details>' in result['message']
    assert {x['pdfId'] for x in result['rag_sources']} == {'A', 'B'}
    refs = grounded_source_map(result['claims'], result['message'])
    assert refs[0]['sourceIds'] == ['a-1', 'b-1']
    assert all(x['method'] == 'literal_quote' and 'confidence' not in x for x in refs)


@pytest.mark.parametrize('case', ['wrong_paper', 'missing_paper', 'invented_quote', 'omitted_cell', 'duplicate_cell'])
def test_invalid_evidence_cannot_become_a_comparison_result(case):
    value = payload()
    if case == 'wrong_paper':
        value['dimensions'][0]['cells'][0]['references'] = value['dimensions'][0]['cells'][1]['references']
    elif case == 'missing_paper':
        value['claims'][0]['references'] = value['claims'][0]['references'][:1]
    elif case == 'invented_quote':
        value['claims'][0]['references'][0]['quote'] = 'This invented quote does not occur in the paper.'
    elif case == 'omitted_cell':
        value['dimensions'][0]['cells'].pop()
    else:
        value['dimensions'][0]['cells'][1] = copy.deepcopy(value['dimensions'][0]['cells'][0])
    with pytest.raises(ValueError):
        call(value)


def test_unknown_cell_has_no_fake_claim_or_source():
    value = payload()
    value['claims'] = []
    value['dimensions'][0]['cells'][1].update(kind='not_covered', summary='原论文没有提供', references=[])
    result = call(value)
    assert '原论文没有提供' not in result['message']
    assert '当前正文片段未覆盖' in result['message']
    assert [x['pdfId'] for x in result['rag_sources']] == ['A']


def test_elliptical_quote_is_rejected_while_separate_literal_refs_are_accepted():
    sources = copy.deepcopy(SOURCES)
    sources[0]['text'] += ' Our second stage prunes redundant Gaussians after recovery.'
    value = payload()
    value['dimensions'][0]['cells'][0]['references'] = [{'sourceId':'a-1',
        'quote':'We maximize the radar SINR... Our second stage prunes redundant Gaussians'}]
    with patch('services.socratic_service._call_guarded_llm', return_value=json.dumps(value)):
        with pytest.raises(ValueError, match='摘录无法在正文中找到'):
            synthesize_comparison('比较', sources, ['A', 'B'])
    value['dimensions'][0]['cells'][0]['references'] = [
        {'sourceId':'a-1', 'quote':'We maximize the radar SINR'},
        {'sourceId':'a-1', 'quote':'Our second stage prunes redundant Gaussians'},
    ]
    with patch('services.socratic_service._call_guarded_llm', return_value=json.dumps(value)):
        result = synthesize_comparison('比较', sources, ['A', 'B'])
    assert len(result['comparisonTable'][0]['cells'][0]['references']) == 2


def test_cancelled_provider_response_is_not_published():
    cancelled = [False]
    def model(*args):
        cancelled[0] = True
        return json.dumps(payload())
    with patch('services.socratic_service._call_guarded_llm', side_effect=model):
        with pytest.raises(OperationCancelled), cancellation_scope(lambda: cancelled[0]):
            synthesize_comparison('比较', SOURCES, ['A', 'B'])
