from copy import deepcopy
from decimal import Decimal

import pytest

from services.deep_research.requested_measurements import measurements, include_requested_measurements


def row(index, text, *, owner='p', version='a'*16, section='Abstract'):
    return {'sourceId':f'{owner}-{version}-{index}','pdfId':owner,
        'text':'Paper: Model with 140 FPS\nSection: '+section+'\nContent:\n'+text,
        'metadata':{'id':owner,'index_version':version,'chunk_index':index,'section_title':section},
        'location':{'page':1,'chunk':index,'section':section}}


def test_equivalent_notation_and_unit_names_keep_exact_value_and_unit_identity():
    assert measurements('17 seconds, 140 FPS, 0.8 ms, 45 MB') == {
        (Decimal(17),'s'),(Decimal(140),'fps'),(Decimal('.8'),'ms'),(Decimal(45),'mb')}
    assert measurements('1.7e1秒 140帧/秒 .80 milliseconds 45MB') == measurements('17 s 140fps .8ms 45MB')
    assert measurements('-0.5dB +10% 17-second') == {(Decimal('-.5'),'db'),(Decimal(10),'%'),(Decimal(17),'s')}
    assert measurements('1024 ms') != measurements('1.024 s')  # No conversion.


@pytest.mark.parametrize('text',['arxiv:2501.12345v2','Model140FPS','date 2026-10-18','1/17s','1,140 FPS','e-3s','17-20s'])
def test_identifiers_fractions_ranges_and_partial_number_suffixes_are_not_measurements(text):
    assert not measurements(text)


def test_exact_requested_pair_is_selected_over_another_location_with_a_different_number():
    top=row(10,'Training takes about 15s per frame and rendering reaches 140 FPS.',section='Conclusion')
    low=row(11,'General benchmark discussion.')
    exact=row(0,'Frame reconstruction takes 17 seconds, with 140 FPS rendering.')
    header_only=row(1,'Unrelated body text.')
    original=deepcopy([top,low,exact,header_only])
    result=include_requested_measurements([top,low],[exact,header_only],
                                          '17 s reconstruction versus 140 FPS','p',2)
    assert [r['sourceId'] for r in result] == [top['sourceId'],exact['sourceId']]
    assert result[1]['text'] == exact['text'] and result[1]['location'] == exact['location']
    assert result[1]['retrievalMode'] == 'indexed_requested_measurement'
    assert [top,low,exact,header_only] == original


@pytest.mark.parametrize('wrong',['foreign','version','duplicate','section','missing'])
def test_owned_version_and_unambiguous_previous_context_are_required(wrong):
    top=row(0,'Overview'); previous=row(5,'This paragraph describes reconstruction.')
    target=row(6,'This takes 17 seconds for each frame.')
    sources=[previous,target]
    if wrong=='foreign':sources=[row(5,'Reconstruction',owner='foreign'),target]
    elif wrong=='version':sources=[row(5,'Reconstruction',version='b'*16),target]
    elif wrong=='duplicate':sources.append(row(5,'Conflicting identity'))
    elif wrong=='section':sources=[row(5,'Reconstruction',section='Other'),target]
    else:sources=[target]
    assert include_requested_measurements([top],sources,'17 seconds','p',3)==[top]


def test_existing_relevant_sources_and_context_pairs_survive_the_original_limit():
    top=row(0,'140 FPS rendering.'); low=row(1,'Overview.')
    previous=row(5,'Reconstruction definition.'); target=row(6,'This takes 17 seconds.')
    result=include_requested_measurements([top,low,previous],[previous,target], '17s and 140FPS','p',3)
    assert len(result)==3 and {r['sourceId'] for r in result}=={top['sourceId'],previous['sourceId'],target['sourceId']}
    assert next(r for r in result if r['sourceId']==previous['sourceId'])['contextForSourceId']==target['sourceId']
    fixed=[{**top,'contextForSourceId':low['sourceId']},low]
    assert include_requested_measurements(fixed,[previous,target],'17s','p',3)==fixed
    assert include_requested_measurements([top,low],[previous,target],'17s','p',2)==[top,low]


def test_at_most_two_slots_and_no_expansion_when_targets_are_already_present():
    top=row(0,'Overview'); rest=[row(i,'Other content') for i in range(1,5)]
    targets=[row(10,'17 seconds'),row(11,'140FPS'),row(12,'45MB')]
    result=include_requested_measurements([top,*rest],targets,'17s 140FPS 45MB','p',5)
    assert len(result)==5 and sum(r.get('retrievalMode')=='indexed_requested_measurement' for r in result)==2
    ready=[top,row(13,'17s and 140FPS')]
    assert include_requested_measurements(ready,targets,'17s and 140FPS','p',5)==ready
    assert include_requested_measurements(ready,targets,'explain the mechanism','p',5)==ready
