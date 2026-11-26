from copy import deepcopy

import pytest

from services.deep_research.comparison_gap_excerpt import extract


@pytest.mark.parametrize(('status', 'excerpt', 'expected'), [
    ('partial', 'explain why frame rates cannot be ranked', 'explain why frame rates cannot be ranked'),
    ('missing', 'explain why frame rates cannot be ranked', 'explain why frame rates cannot be ranked'),
    ('covered', 'explain why frame rates cannot be ranked', None),
    ('partial', 'invent a new premise', None),
    ('partial', 'Compare the results and explain why frame rates cannot be ranked.', None),
    ('partial', 'ranked', None),
    ('partial', None, None),
])
def test_comparison_gap_locator_can_only_quote_an_unmet_user_clause(status, excerpt, expected):
    question = 'Compare the results and explain why frame rates cannot be ranked.'
    row = {'obligationId': 'answer_scope', 'checks': [
        {'checkId': 'request', 'status': status, 'bindings': [], 'missingRequestExcerpt': excerpt},
    ]}
    rows = [row]
    snapshot = deepcopy(rows)
    cleaned, located, note = extract(rows, 'answer_scope', question)
    assert located == expected
    assert note is None
    assert cleaned == [{'obligationId': 'answer_scope', 'checks': [
        {'checkId': 'request', 'status': status, 'bindings': []},
    ]}]
    assert rows == snapshot


@pytest.mark.parametrize(('status', 'excerpt', 'explain', 'has_note'), [
    ('partial', '解释两种方案的部署取舍', True, True),
    ('partial', '添加另一篇论文的结果', True, False),
    ('covered', '解释两种方案的部署取舍', True, False),
    ('partial', '解释两种方案的部署取舍', False, False),
])
def test_model_explanation_is_optional_metadata_only_for_a_located_gap(status, excerpt, explain, has_note):
    note = '答案没有解释额外处理与部署收益的关系。'
    rows = [{'obligationId': 'answer_scope', 'checks': [
        {'checkId': 'request', 'status': status, 'bindings': [],
         'missingRequestExcerpt': excerpt, 'missingAnswerElement': note},
    ]}]
    cleaned, _, diagnostic = extract(rows, 'answer_scope', '面向初学者解释两种方案的部署取舍。', explain=explain)
    assert (diagnostic == note) is has_note
    assert cleaned[0]['checks'][0]['status'] == status
    assert ('missingAnswerElement' in cleaned[0]['checks'][0]) is not explain
