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
    cleaned, located = extract(rows, 'answer_scope', question)
    assert located == expected
    assert cleaned == [{'obligationId': 'answer_scope', 'checks': [
        {'checkId': 'request', 'status': status, 'bindings': []},
    ]}]
    assert rows == snapshot
