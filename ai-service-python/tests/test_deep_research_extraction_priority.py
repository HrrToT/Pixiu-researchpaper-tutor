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


def test_complete_method_operation_precedes_causal_words_in_dataset_or_summary_prose():
    general = passage('summary', 'a', 'When gradients change the input, predictions and losses improve.')
    method = passage('method', 'a', 'Parameters remain fixed while opacity is optimized to adjust its influence.')
    method[1]['section'] = '3.2 Methodology'
    general[1]['section'] = 'Dataset'
    before = deepcopy((general, method))
    selected = prioritize_extraction_passages([general, method], obligations())
    assert selected[0][0]['sourceId'] == 'method'
    assert (general, method) == before


def test_method_heading_alone_does_not_displace_a_complete_explanation():
    heading = passage('heading', 'a', 'The methodology introduces a model and names three modules.')
    heading[1]['section'] = 'Methodology'
    causal = passage('causal', 'a', 'When the loss gradient updates a parameter, predictions change.')
    assert prioritize_extraction_passages([heading, causal], obligations())[0][0]['sourceId'] == 'causal'


def test_requested_literal_measurement_precedes_generic_method_operations_in_version_three():
    rows=[passage('method','a','When the loss gradient updates weights, later predictions change.'),
          passage('conclusion','a','Rendering reaches 140 FPS after 15 seconds of training.'),
          passage('requested','a','Reconstruction takes 17 seconds and rendering reaches 140 FPS.')]
    rows[0][1]['section']='Method'
    obs={'measure':{'obligationId':'measure','question':'Explain the operations for 17 seconds and 140 FPS.',
        'searchQuery':'reconstruction 17s rendering 140FPS','requiredSources':['a'],
        'completionCriteria':[{'responseType':'explanation'}]}}
    before=deepcopy(rows)
    assert prioritize_extraction_passages(rows,obs,2)[0][0]['sourceId']=='method'
    assert prioritize_extraction_passages(rows,obs,3)[0][0]['sourceId']=='requested'
    assert rows==before


def test_necessary_rationale_gets_its_first_slot_without_metadata_header_bias():
    intro=passage('intro','a','Paper: Since this method requires essential input updates\nContent:\nThe model is trained using its prior representation.')
    operation=passage('operation','a','When inputs change, a network updates parameters to predict output.')
    operation[1]['section']='Method'
    reason=passage('reason','a','Since existing primitives cannot represent newly observed regions, adding new primitives is necessary.')
    obs={'how':{'obligationId':'how','question':'How does the model update its representation?',
        'searchQuery':'model update representation','requiredSources':['a'],'completionCriteria':[{'responseType':'explanation'}]},
         'why':{'obligationId':'why','question':'Why is adding new primitives necessary?',
        'searchQuery':'adding new primitives observed regions','requiredSources':['a'],'completionCriteria':[{'responseType':'explanation'}]}}
    rows=[intro,operation,reason]; before=deepcopy(rows)
    first=prioritize_extraction_passages(rows,obs,3)[:2]
    assert {r[0]['sourceId'] for r in first}=={'operation','reason'}
    assert rows==before


def test_literal_priority_keeps_paper_balance_and_does_not_grant_foreign_scope():
    rows=[passage('a1','a','17 seconds'),passage('a2','a','17 seconds and 140FPS'),
          passage('b1','b','A separate authorized method description.'),passage('foreign','x','17 seconds and 140FPS')]
    obs=obligations(); obs['training']['question']='Explain 17s and 140FPS'
    obs['training']['requiredSources']=['a','b']
    selected=prioritize_extraction_passages(rows,obs,3)
    assert {r[0]['workId'] for r in selected[:2]}=={'a','b'}
    assert selected[-1][0]['sourceId']=='foreign'
