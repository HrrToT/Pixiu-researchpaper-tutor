from copy import deepcopy

import pytest

from services.deep_research.named_source_rows import include_requested_rows


def row(identity, text, **metadata):
    return {'sourceId': identity, 'pdfId': 'paper', 'text': text,
            'metadata': {'id': 'paper', 'index_version': 'a'*16, **metadata},
            'location': {'page': 4}, 'contentHash': identity + '-hash', 'versionId': 'v1'}


def caption(identity='named'):
    return row(identity, 'Table caption: Synthetic dataset scene measurements.\nTable row 2: Hotdog | 0.2 | 30')


def test_named_scene_displaces_low_priority_hit_without_expanding_capacity_or_approving_numbers():
    top, other, named = row('top','Relevant method prose'), row('other','Generic data overview'), caption()
    original = deepcopy((top, other, named))
    result = include_requested_rows([top,other], [named], 'Use hotdog scene', 'paper', 2)
    assert [item['sourceId'] for item in result] == ['top','named']
    assert result[1]['text'] == named['text'] and result[1]['location'] == named['location']
    assert result[1]['contentHash'] == named['contentHash']
    assert result[1]['retrievalMode'] == 'indexed_requested_row'
    assert 'verification' not in result[1]
    assert (top,other,named) == original


@pytest.mark.parametrize('change', [{'pdfId':'foreign'}, {'metadata':{'id':'foreign'}},
                                  {'metadata':{'index_version':'b'*16}},
                                  {'text':'Table caption: Synthetic data.\nTable row 2: HotdogExtra | 1 | 2'},
                                  {'text':'The Hotdog scene appears somewhere without a located table caption.'}])
def test_owner_version_or_literal_label_mismatch_does_not_gain_a_slot(change):
    top, other, named = row('top','Method'), row('other','Background'), caption()
    for key,value in change.items():
        if key=='metadata': named[key].update(value)
        else: named[key]=value
    assert include_requested_rows([top,other],[named],'hotdog','paper',2) == [top,other]


def test_duplicate_candidate_identity_is_not_resolved_arbitrarily():
    top, other, named = row('top','Method'), row('other','Background'), caption()
    assert include_requested_rows([top,other],[named,deepcopy(named)],'hotdog','paper',2) == [top,other]


def test_named_target_and_context_pair_outrank_an_extra_generic_hit():
    top, previous, anchor = row('top','Best method'), row('previous','Definitions'), row('anchor','where F...')
    previous['contextForSourceId']='anchor'
    result = include_requested_rows([top,previous,anchor],[caption()],'hotdog','paper',3)
    assert [r['sourceId'] for r in result] == ['previous','anchor','named']


def test_context_pair_is_not_broken_when_only_two_slots_exist():
    previous, anchor = row('previous','Definitions'), row('anchor','where F...')
    previous['contextForSourceId']='anchor'
    assert include_requested_rows([previous,anchor],[caption()],'hotdog','paper',2) == [previous,anchor]


def test_existing_named_row_is_not_duplicated_or_displaced_by_a_second_name():
    top, named, low = row('top','Method'), caption(), row('low','Background')
    other = row('other','Table caption: Synthetic data.\nTable row 3: Chair | 1 | 2')
    result = include_requested_rows([top,named,low],[named,other],'hotdog and Chair','paper',3)
    assert [item['sourceId'] for item in result] == ['top','named','other']


def test_missing_index_identity_or_single_slot_disables_expansion():
    top = row('top','Method',index_version='')
    assert include_requested_rows([top],[caption()],'hotdog','paper',2) == [top]
    top = row('top','Method')
    assert include_requested_rows([top],[caption()],'hotdog','paper',1) == [top]


def test_rare_requested_scene_outranks_repeated_paper_method_name():
    top, previous, anchor = row('top','Paper: ExampleNet. Best method'), row('previous','Paper: ExampleNet. Definitions'), row('anchor','Paper: ExampleNet. where F...')
    previous['contextForSourceId']='anchor'
    method = row('method','Paper: ExampleNet.\nTable caption: Overall benchmark.\nTable row 1: ExampleNet | 1 | 2')
    scene = caption()
    scene['text'] = 'Paper: ExampleNet.\n' + scene['text']
    result = include_requested_rows([top,previous,anchor],[top,previous,anchor,method,scene],
                                   'ExampleNet hotdog scene evaluation','paper',3)
    assert [r['sourceId'] for r in result] == ['previous','anchor','named']
