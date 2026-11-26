from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests

from services.deep_research.contracts import DeepResearchError
from services.deep_research.located_evidence import located_evidence_factory
from services.deep_research.verification import make_evidence

QUOTE = 'Each anchor predicts attributes from the camera direction and distance.'


def setup():
    source = dict(workId='paper', versionId='v1', contentHash='chunk-hash', accessLevel='fulltext')
    record = {'materials': [{'materialId': 'paper', 'versionId': 'v1', 'contentHash': 'pdf-hash'}],
              'state': {'sources': [], 'evidence': [{'location': {'page': 1}}]}}
    repo = Mock()
    repo.require_run.return_value = record
    local = Mock()
    local.load_pages.return_value = (record['materials'][0], [{'page': 2, 'text': QUOTE}])
    return located_evidence_factory(repo, 'run', local), source, record, local


def test_new_identity_uses_physical_page_without_mutating_history():
    create, source, record, local = setup()
    before = deepcopy(record)
    args = dict(source=source, quote=QUOTE, original=QUOTE, location={'page': 1, 'section': 'Introduction'},
                obligation_ids=['o'])
    old = make_evidence(**args)
    new = create(**args)
    assert new['location']['page'] == 2
    assert new['location']['pageResolution'] == 'exact'
    assert new['evidenceId'] != old['evidenceId']
    assert new['quote'] == old['quote'] and new['verification']['literal'] == 'passed'
    assert record == before and args['location']['page'] == 1
    local.load_pages.assert_called_once_with('paper')


@pytest.mark.parametrize('error', [DeepResearchError('scope_revoked', 'revoked'),
                                  DeepResearchError('source_changed', 'changed')])
def test_scope_and_version_failures_are_not_hidden(error):
    create, source, _, local = setup()
    local.load_pages.side_effect = error
    with pytest.raises(DeepResearchError):
        create(source, QUOTE, QUOTE, location={'page': 1}, obligation_ids=['o'])


@pytest.mark.parametrize('error', [DeepResearchError('source_unavailable', 'unavailable'), requests.Timeout()])
def test_unavailable_pdf_does_not_publish_stale_page(error):
    create, source, _, local = setup()
    local.load_pages.side_effect = error
    ev = create(source, QUOTE, QUOTE, location={'page': 1}, obligation_ids=['o'])
    assert 'page' not in ev['location']
    assert ev['location']['pageResolution'] == 'unresolved'


def test_external_abstract_does_not_fetch_task_pdf():
    create, source, _, local = setup()
    source.update(workId='external', accessLevel='abstract')
    ev = create(source, QUOTE, QUOTE, location={'section': 'Abstract'}, obligation_ids=['o'])
    assert ev['location'] == {'section': 'Abstract'}
    local.load_pages.assert_not_called()


def test_only_verified_serialized_table_row_preserves_geometry():
    create, source, record, local = setup()
    quote = 'Table row 1: Ours | 120'
    packet = {'groups': [['Scenes', ['FPS']]], 'rows': [[1, 'Ours', ['120']]]}
    record['state']['sources'] = [{**source, 'tableData': packet}]
    location = {'page': 8, 'table': 't1', 'bbox': [0, 0, 1, 1]}
    ev = create(source, quote, quote, location=location, obligation_ids=['o'])
    assert ev['location'] == location
    local.load_pages.assert_not_called()
    record['state']['sources'][0]['tableData'] = None
    ev = create(source, quote, quote, location=location, obligation_ids=['o'])
    assert 'page' not in ev['location']


@pytest.mark.parametrize('version, change, expected_page', [
    (2, None, 6), (1, None, None), (2, 'page', None), (2, 'source', None),
])
def test_only_matching_owned_pdf_table_passage_retains_page(version, change, expected_page):
    from services.deep_research.local_sources import LocalTaskRetriever

    create, source, record, local = setup()
    material, = record['materials']
    source['contentHash'] = material['contentHash']
    record['comparisonPdfTableFallbackVersion'] = version
    packet = {'groups': [['Scenes', ['FPS']]], 'rows': [[2, 'Baseline', ['60']], [3, 'Ours', ['120']]]}
    page = {'page': 6, 'verifiedTables': [{'number': '1', 'caption': 'Comparison', 'tableData': packet}]}
    table, = LocalTaskRetriever._pdf_passages('paper', material, [page])
    row = {**table, **source}
    record['state']['sources'] = [row]
    location = {**table['location'], 'sourcePassageStart': 0, 'sourcePassageEnd': len(table['text'])}
    if change == 'page':
        location.update(page=9, pageIndex=8)
    if change == 'source':
        row['sourceId'] = 'other-table'
    evidence = create(source, table['text'], table['text'], location=location, obligation_ids=['o'])
    assert evidence['location'].get('page') == expected_page
    assert local.load_pages.call_count == (0 if expected_page else 1)


def test_page_match_does_not_bypass_literal_evidence_check():
    create, source, _, _ = setup()
    with pytest.raises(ValueError, match='Quotation'):
        create(source, QUOTE, 'Different original', location={'page': 1}, obligation_ids=['o'])


def test_page_batch_reuses_physical_pages_only_inside_its_explicit_scope():
    from services.deep_research.text_quality import guard
    create, source, record, local = setup()
    record['sourceGlyphContractVersion'] = 1
    create = guard(create, record)
    args = dict(location={'page':1}, obligation_ids=['o'])
    with create.physical_page_batch():
        first = create(source, QUOTE, QUOTE, **args)
        second = create(source, QUOTE, QUOTE, **args)
        assert first == second
        assert local.load_pages.call_count == 1
    create(source, QUOTE, QUOTE, **args)
    assert local.load_pages.call_count == 2
    with create.physical_page_batch():
        create(source, QUOTE, QUOTE, **args)
    assert local.load_pages.call_count == 3


def test_failed_page_load_is_not_cached_and_scope_revocation_is_rechecked_after_batch():
    create, source, _, local = setup()
    success = local.load_pages.return_value
    local.load_pages.side_effect = [requests.Timeout(), success]
    args = dict(location={'page':1}, obligation_ids=['o'])
    with create.physical_page_batch():
        assert create(source, QUOTE, QUOTE, **args)['location']['pageResolution'] == 'unresolved'
        assert create(source, QUOTE, QUOTE, **args)['location']['page'] == 2
        assert create(source, QUOTE, QUOTE, **args)['location']['page'] == 2
        assert local.load_pages.call_count == 2
    local.load_pages.side_effect = DeepResearchError('scope_revoked','revoked')
    with pytest.raises(DeepResearchError):create(source, QUOTE, QUOTE, **args)


def test_page_batch_is_cleared_after_a_failed_quotation():
    create, source, _, local = setup()
    with pytest.raises(ValueError):
        with create.physical_page_batch():
            create(source, QUOTE, 'Wrong original', location={'page':1}, obligation_ids=['o'])
    create(source, QUOTE, QUOTE, location={'page':1}, obligation_ids=['o'])
    assert local.load_pages.call_count == 2


def test_batch_does_not_share_pages_between_owners_with_the_same_pdf_hash():
    create, source, record, local = setup()
    record['materials'].append({**record['materials'][0], 'materialId':'other'})
    local.load_pages.side_effect = [
        (record['materials'][0], [{'page':2,'text':QUOTE}]),
        (record['materials'][1], [{'page':7,'text':QUOTE}])]
    with create.physical_page_batch():
        first=create(source, QUOTE, QUOTE, location={'page':1}, obligation_ids=['o'])
        second=create({**source,'workId':'other'}, QUOTE, QUOTE,
                      location={'page':1}, obligation_ids=['o'])
    assert first['location']['page']==2 and second['location']['page']==7
    assert local.load_pages.call_count==2 and first['sourceWorkId']!=second['sourceWorkId']


def test_changed_snapshot_hash_cannot_reuse_an_earlier_batch_entry():
    create, source, record, local = setup()
    with create.physical_page_batch():
        create(source, QUOTE, QUOTE, location={'page':1}, obligation_ids=['o'])
        record['materials'][0]['contentHash']='different-pdf-hash'
        local.load_pages.side_effect=DeepResearchError('source_changed','changed')
        with pytest.raises(DeepResearchError):
            create(source, QUOTE, QUOTE, location={'page':1}, obligation_ids=['o'])
    assert local.load_pages.call_count==2
