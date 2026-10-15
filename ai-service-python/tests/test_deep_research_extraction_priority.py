from copy import deepcopy

from services.deep_research.extraction_priority import prioritize_extraction_passages


def passage(key, paper, text, origin='lookup'):
    return ({'sourceId': key, 'workId': paper, 'versionId': paper + '-v1',
             'accessLevel': 'fulltext', 'title': 'Paper: Topic', 'obligationIds': [origin]},
            {'page': 2, 'offset': 100}, text)


def obligations(kind='explanation'):
    return {'training': {'obligationId': 'training', 'question': 'How is the model trained?',
                        'searchQuery': 'model training prediction', 'requiredSources': ['a', 'b', 'c'],
                        'completionCriteria': [{'criterionId': 'path', 'responseType': kind,
                                                'requirement': 'Explain the parameter update path.'}]}}


def test_later_conditional_update_passage_is_in_the_first_bounded_batch_without_mutation():
    rows = [passage('background', 'a', 'Prediction model training names. ' * 20),
            passage('method', 'a', 'When the loss gradient increases a parameter, later predictions change.'),
            passage('definition', 'a', 'A model maps inputs to predictions.')]
    before = deepcopy(rows)
    selected = prioritize_extraction_passages(rows, obligations())
    assert selected[0][0]['sourceId'] == 'method'
    assert {row[0]['sourceId'] for row in selected} == {row[0]['sourceId'] for row in rows}
    assert rows == before and selected[0][2] == rows[1][2]


def test_first_batch_balances_actual_papers_even_when_one_has_more_high_scoring_passages():
    text = 'When the loss gradient increases a parameter, subsequent output changes.'
    rows = [passage('a1', 'a', text), passage('a2', 'a', text), passage('a3', 'a', text),
            passage('b1', 'b', 'A separate method description.'), passage('c1', 'c', 'A third source description.')]
    selected = prioritize_extraction_passages(rows, obligations())
    assert {row[0]['workId'] for row in selected[:3]} == {'a', 'b', 'c'}
    assert len(selected) == len(rows)


def test_query_origin_does_not_prevent_an_authorized_passage_supporting_an_explanation():
    rows = [passage('early', 'a', 'A short definition.'),
            passage('late', 'a', 'If the input changes, the loss gradient updates weights and predictions.', origin='other-query')]
    assert prioritize_extraction_passages(rows, obligations())[0][0]['sourceId'] == 'late'


def test_identification_only_order_is_unchanged_and_unrelated_sources_get_no_explanation_priority():
    rows = [passage('early', 'a', 'A definition.'),
            passage('late', 'a', 'When the loss gradient updates weights, predictions change.')]
    assert prioritize_extraction_passages(rows, obligations('identification')) == rows
    outside = passage('outside', 'not-permitted', 'When the loss gradient updates weights, predictions change.')
    allowed = passage('allowed', 'a', 'When an input changes, model output changes.')
    # The selector never grants authority: the caller filters disallowed sources
    # first; their lexical signal cannot become an authorized explanation score.
    assert prioritize_extraction_passages([outside, allowed], obligations())[0][0]['sourceId'] == 'allowed'
