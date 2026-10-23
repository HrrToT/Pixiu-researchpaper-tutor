from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.source_continuity import (
    enabled, illustrative_reference, needs_preceding_context, include_preceding_context)
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.graph import make_read_node
from test_deep_research_source_continuity import row


@pytest.mark.parametrize('text', ['In Fig.6, we compare the two configurations.',
    'In Figure 12 we show new content.', 'As shown in Fig. 4, the experiment differs.',
    'As illustrated in Table 2 the results differ.', 'As in Fig. 6(a), we compare variants.',
    '在图6中比较两种方法。', '如表 2 所示，比较配置。'])
def test_leading_illustrative_reference_is_versioned_and_headers_are_not_the_subject(text):
    source = row(38, 'Paper: Example\nSection: Evaluations\nContent:\n' + text)
    assert illustrative_reference(source) and needs_preceding_context(source, illustrative=True)
    assert not needs_preceding_context(source)


@pytest.mark.parametrize('text', ['We evaluate two methods.', 'Paper: In Fig.6\nContent: We use images.',
    'The method is described in Fig.6.', 'In FigureX the input differs.', '', None])
def test_nonleading_missing_or_ambiguous_reference_does_not_borrow_a_neighbor(text):
    assert not illustrative_reference({'text': text})


def test_new_context_keeps_separate_original_identity_hash_location_and_bounded_best_hit():
    best = row(31, 'We evaluate a dataset.', section='Datasets')
    anchor = row(38, 'In Fig.6, the proposed configurations capture new objects.', section='Evaluations')
    prior = row(37, 'The Cedar scene belongs to ExampleDataset.', section='Evaluations')
    prior['contentHash'] = 'own-original-hash'
    low = row(58, 'Another table.', section='Results')
    before = deepcopy((best, anchor, prior, low))
    old = include_preceding_context([best, low, anchor], [prior], 'paper', 3)
    new = include_preceding_context([best, low, anchor], [prior], 'paper', 3, illustrative=True)
    assert old == [best, low, anchor]
    assert [s['sourceId'] for s in new] == [best['sourceId'], prior['sourceId'], anchor['sourceId']]
    assert new[1] == {**prior, 'contextForSourceId': anchor['sourceId'], 'retrievalMode': 'indexed_preceding_context'}
    assert (best, anchor, prior, low) == before
    assert include_preceding_context([best, anchor], [prior], 'paper', 2, illustrative=True) == [best, anchor]


@pytest.mark.parametrize('change', ['owner', 'index_version', 'section', 'bool_chunk', 'forged_id', 'anchor_id', 'duplicate'])
def test_new_context_cannot_cross_ownership_family_section_or_ambiguous_identity(change):
    anchor = row(38, 'In Fig.6, we compare methods.')
    prior = row(37, 'A named scene belongs to a dataset.')
    candidates = [prior]
    if change == 'owner': prior['pdfId'] = 'foreign'
    elif change == 'index_version': prior['metadata']['index_version'] = 'b' * 16
    elif change == 'section': prior['metadata']['section_title'] = 'Other'
    elif change == 'bool_chunk': prior['metadata']['chunk_index'] = True
    elif change == 'forged_id': prior['sourceId'] = 'foreign-v' + 'a' * 16 + '-chunk-37'
    elif change == 'anchor_id': anchor['sourceId'] = 'forged'
    elif change == 'duplicate': candidates.append(deepcopy(prior))
    assert include_preceding_context([anchor], candidates, 'paper', 2, illustrative=True) == [anchor]


def normalized(index, text):
    source = row(index, text, owner='p', section='Evaluations')
    return {**source, 'workId': 'p', 'versionId': 'v', 'ownerMaterialId': 'p',
        'accessLevel': 'fulltext', 'contentHash': 'hash-' + str(index), 'obligationIds': ['o']}


@pytest.mark.parametrize('change', ['none', 'abstract', 'location', 'version', 'owner'])
def test_read_bundles_only_the_actual_owned_fulltext_neighbor(monkeypatch, change):
    monkeypatch.setattr('services.deep_research.reading_priority.prioritize_extraction_passages', lambda rows, *_: rows)
    anchor = normalized(38, 'In Fig.6, compare these approaches.')
    prior = normalized(37, 'A scene of the named dataset.')
    if change == 'abstract': prior['accessLevel'] = 'abstract'
    elif change == 'location': prior['location']['chunk'] = True
    elif change == 'version': prior['versionId'] = 'other'
    elif change == 'owner': prior['ownerMaterialId'] = 'other'
    selected = select_read_sources([anchor, prior], {'o': {'obligationId': 'o', 'requiredSources': ['p']}},
        2, illustrative_context=True)
    # For invalid context it may be independently readable, but cannot be
    # bundled before the anchor as that anchor's same-source context.
    assert selected == ([prior, anchor] if change == 'none' else [anchor, prior])


def test_new_graph_reads_the_real_neighbor_within_twelve_slots_without_changing_sources(monkeypatch):
    monkeypatch.setattr('services.deep_research.reading_priority.prioritize_extraction_passages', lambda rows, *_: rows)
    anchor = normalized(38, 'In Fig.6, we evaluate new objects.')
    prior = normalized(37, 'The selected scene belongs to the named dataset.')
    sources = [anchor, *[normalized(i, 'Other original text.') for i in range(11)], prior]
    def run(version):
        record = {'readingPriorityContractVersion': 5, 'sourceContinuityContractVersion': version,
            'state': {'sources': sources, 'plan': [{'obligations': [{'obligationId': 'o', 'requiredSources': ['p']}]}]},
            'budget': {'profile': 'standard'}}
        read = []
        def update(_id, change, **kw):
            nonlocal record
            record = change(deepcopy(record)); return deepcopy(record)
        def reader(_id, sid):
            source = next(s for s in sources if s['sourceId'] == sid); read.append(sid)
            return {'accessLevel': 'fulltext', 'pages': [{'page': 5, 'text': source['text']}]}
        make_read_node(reader, lambda *_: True, update)({'run_id': 'r', 'source_ids': [s['sourceId'] for s in sources]})
        assert len(read) == 12 and record['state']['sources'] == sources
        return read, record['state']['readResults']
    old, _ = run(0); new, results = run(1)
    assert prior['sourceId'] not in old and new[:2] == [prior['sourceId'], anchor['sourceId']]
    actual = next(r for r in results if r['sourceId'] == prior['sourceId'])
    assert actual['pages'][0]['text'] == prior['text']
    assert not actual.get('verification')  # Reading is not a factual verdict.


@pytest.mark.parametrize('version', [0, 1])
def test_local_retrieval_applies_new_context_after_other_selectors_and_keeps_cache(monkeypatch, version):
    from services.tools import retrieval_tools
    from test_deep_research_local_sources import fixture
    local, _get, _parse, _validate = fixture(monkeypatch)
    local.repo.require_run.return_value.update(sourcePrecisionContractVersion=8,
        sourceContinuityContractVersion=version, state={'plan': []})
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda _: object())
    def doc(index, text, section='Evaluations'):
        return {'text': text, 'metadata': {'id': 'p', 'index_version': 'a' * 16,
            'chunk_index': index, 'section_title': section, 'page': 5}}
    hits = [doc(31, 'Overview.', 'Datasets'), doc(58, 'Another result.'), doc(38, 'In Fig.6, compare alternatives.')]
    prior = doc(37, 'The selected named scene belongs to ExampleDataset.')
    rag = Mock(); rag.normalize_id.side_effect = lambda v: v; rag.get_documents_by_metadata.return_value = [*hits, prior]
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: rag)
    retrieve = Mock(return_value=hits); monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', retrieve)
    # Verify composition order: a criterion selector that returns its original
    # envelope cannot erase the subsequent bounded continuity expansion.
    monkeypatch.setattr('services.deep_research.criterion_sources.include_indexed_criteria', lambda rows, *_a, **_k: rows)
    for _ in range(2):
        result = local('ablation approaches', 'p', limit=3)
        assert len(result) == 3
        assert (37 in {r['location']['chunk'] for r in result}) is (version == 1)
    rag.get_documents_by_metadata.assert_called_once_with({'id': 'p'}, limit=400)
    assert retrieve.call_count == 2


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 3])
def test_continuity_contract_is_server_owned_immutable_and_strict(tmp_path, replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        value, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Read a paper',
            'sourceContinuityContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert value['sourceContinuityContractVersion'] == 2 and enabled(value)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(value['runId'], lambda r: {**r, 'sourceContinuityContractVersion': replacement})
    finally:
        facade.shutdown()
    assert not enabled({'sourceContinuityContractVersion': replacement})
