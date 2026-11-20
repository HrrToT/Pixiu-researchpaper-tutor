from copy import deepcopy
from unittest.mock import Mock

from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_acquire_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.source_labels import source_display_title


def test_hash_title_falls_back_to_original_filename_without_replacing_real_titles():
    opaque = 'a' * 64 + '.pdf'
    assert source_display_title(opaque, '2401.00001v2.pdf') == '2401.00001v2.pdf'
    assert source_display_title('Research method', 'upload.pdf') == 'Research method'
    assert source_display_title(opaque) == opaque  # No invented title when no readable label exists.
    assert source_display_title(None, '') == ''


def test_snapshot_and_retrieved_source_keep_readable_label_and_original_identity(tmp_path):
    opaque = 'a' * 64 + '.pdf'
    snapshot = {'materialRefs': [opaque], 'materialVersions': [{
        'id': opaque, 'title': opaque, 'fileName': '2401.00001v2.pdf',
        'versionId': 'fixed-version', 'contentHash': 'fixed-hash'}]}
    before = deepcopy(snapshot)
    repo = DeepResearchRepository(str(tmp_path/'research.sqlite3'))
    repo.initialize()
    facade = ResearchFacade(repo=repo, graph_factory=Mock(), llm_client=Mock())
    try:
        record, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o',
            'question': 'Explain the method.', 'materialSnapshot': snapshot}, start_async=False)
        record = repo.begin_execution(record['runId'])
        material = record['materials'][0]
        assert material['title'] == '2401.00001v2.pdf'
        assert material['materialId'] == opaque and material['versionId'] == 'fixed-version'
        assert record['materialSnapshot'] == snapshot == before
        record['state'] = {'plan': [{'obligations': [{'obligationId': 'q', 'question': 'Explain',
                                                     'requiredSources': [opaque]}]}]}
        def update(_, change, **kwargs):
            nonlocal record
            record = change(record)
            return record
        retrieve = Mock(return_value=[{'sourceId': 's', 'pdfId': opaque, 'title': opaque,
                                       'text': 'Actual method passage.', 'contentHash': 'passage-hash'}])
        make_acquire_node(retrieve, lambda *args: True, update)({'run_id': record['runId']})
        source = record['state']['sources'][0]
        assert source['title'] == '2401.00001v2.pdf'
        assert source['workId'] == opaque and source['versionId'] == 'fixed-version'
        assert source['text'] == 'Actual method passage.'
    finally:
        facade.shutdown(wait=True)
