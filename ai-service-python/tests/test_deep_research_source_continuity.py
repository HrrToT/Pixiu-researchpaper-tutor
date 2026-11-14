from copy import deepcopy
import pytest
from services.deep_research.source_continuity import include_preceding_context, needs_preceding_context


def row(index, text, *, owner='paper', version='a' * 16, section='Method'):
    return {'sourceId': f'{owner}-v{version}-chunk-{index}', 'pdfId': owner, 'text': text,
            'location': {'page': 5, 'chunk': index, 'section': section},
            'metadata': {'id': owner, 'index_version': version, 'chunk_index': index, 'section_title': section}}


def test_predecessor_is_separate_and_preserves_anchor_best_hit_and_limit():
    head = row(0, 'Overview.')
    low = row(9, 'Other discussion.')
    anchor = row(16, 'Paper: Example\nSection: Method\nContent:\nwhere F maps the inputs to outputs.')
    previous = row(15, 'The inputs are images and calibrated projection matrices.')
    original = deepcopy([head, low, anchor, previous])
    result = include_preceding_context([head, low, anchor], [previous], 'paper', 3)
    assert [r['sourceId'] for r in result] == [head['sourceId'], previous['sourceId'], anchor['sourceId']]
    assert result[1]['text'] == previous['text'] and result[2]['text'] == anchor['text']
    assert result[1]['location'] == previous['location']
    assert result[1]['contextForSourceId'] == anchor['sourceId']
    assert [head, low, anchor, previous] == original


@pytest.mark.parametrize('change', [{'pdfId': 'foreign'}, {'metadata': {'id': 'foreign'}},
    {'metadata': {'index_version': 'b' * 16}}, {'metadata': {'section_title': 'Related Work'}},
    {'metadata': {'chunk_index': True}}])
def test_wrong_owner_version_section_or_index_is_not_borrowed(change):
    anchor, previous = row(16, 'where F maps inputs.'), row(15, 'Input definitions.')
    for key, value in change.items():
        if key == 'metadata':
            previous[key].update(value)
        else:
            previous[key] = value
    assert include_preceding_context([anchor], [previous], 'paper', 2) == [anchor]


def test_ambiguous_missing_or_already_selected_context_never_expands_again():
    anchor, previous = row(16, 'where F maps inputs.'), row(15, 'Definitions.')
    assert include_preceding_context([anchor], [previous, previous], 'paper', 2) == [anchor]
    assert include_preceding_context([anchor], [], 'paper', 2) == [anchor]
    assert include_preceding_context([previous, anchor], [previous], 'paper', 2) == [previous, anchor]
    assert include_preceding_context([anchor], [previous], 'paper', 1) == [anchor]


def test_complete_paragraph_does_not_trigger_unrelated_context_fetch():
    assert not needs_preceding_context(row(1, 'Our model takes two images.'))
    assert needs_preceding_context(row(1, 'In contrast, this method uses a different condition.'))
