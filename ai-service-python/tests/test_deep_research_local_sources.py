import hashlib
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.local_sources import LocalTaskRetriever


def fixture(monkeypatch, *, changed=False, valid=True):
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: None)
    original = b'%PDF-existing-authorized-paper'
    repo = Mock()
    repo.require_run.return_value = {'taskId': 'task/中文', 'materials': [{
        'materialId': 'p', 'title': 'Paper', 'contentHash': hashlib.sha256(original).hexdigest()}]}
    response = Mock(status_code=200)
    response.iter_content.return_value = [b'%PDF-changed' if changed else original]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    get = Mock(return_value=response)
    parse = Mock(return_value=[{'page': 1, 'text': 'Unrelated introduction.'},
                              {'page': 4, 'text': 'Ablation fixes the dataset and camera split for Gaussian pruning.'}])
    validate = Mock(return_value=valid)
    return LocalTaskRetriever(repo, 'r', validate, origin='http://127.0.0.1:8081/api', get=get, parse=parse), get, parse, validate


def test_fallback_reads_only_hashed_owned_pdf_and_preserves_exact_page(monkeypatch):
    local, get, parse, validate = fixture(monkeypatch)
    found = local('Gaussian pruning ablation', 'p')
    assert len(found) == 1 and found[0]['location']['page'] == 4
    assert found[0]['text'] == parse.return_value[1]['text']
    assert found[0]['retrievalMode'] == 'pdf_lexical_fallback'
    assert '/task%2F%E4%B8%AD%E6%96%87/materials/p/file' in get.call_args.args[0]
    assert get.call_args.kwargs['allow_redirects'] is False
    assert local('camera split', 'p')
    assert get.call_count == parse.call_count == 1
    validate.return_value = False
    with pytest.raises(DeepResearchError, match='范围'):
        local('again', 'p')
    assert get.call_count == 1


def test_changed_bytes_never_reach_parser(monkeypatch):
    local, _, parse, _ = fixture(monkeypatch, changed=True)
    with pytest.raises(DeepResearchError, match='快照'):
        local('pruning', 'p')
    parse.assert_not_called()


def test_indexed_retrieval_disables_untracked_query_rewrite_through_registry(monkeypatch):
    from services.tools import retrieval_tools
    from rag.store import DummyRAG
    local, get, parse, _ = fixture(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    retrieve = Mock(return_value=[{'text': 'Gaussian pruning evidence from the indexed paper.',
                                  'metadata': {'id': 'p', 'page': 4}, 'similarity': 0.9}])
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: DummyRAG())
    monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', retrieve)
    found = local('高斯剪枝', 'p')
    assert found and found[0]['pdfId'] == 'p'
    assert found[0]['location']['page'] == 4
    assert found[0]['retrievalMode'] == 'indexed_hybrid'
    retrieve.assert_called_once_with('高斯剪枝', top_k=8, filter_metadata={'id': 'p'}, allow_query_rewrite=False)
    get.assert_not_called()
    parse.assert_not_called()


def test_indexed_locations_preserve_page_zero_and_table_uncertainty():
    from services.deep_research.local_sources import _indexed_source
    item = _indexed_source({'pageIndex': 0, 'chunkIndex': 0, 'metadata': {
        'section_title': 'Main results', 'table_id': 't1', 'table_column_mapping_unverified': True}})
    assert item['location'] == {'page': 1, 'chunk': 0, 'section': 'Main results',
                                'table': 't1', 'tableColumnMappingUnverified': True}
    assert 'page' not in _indexed_source({'metadata': {}})['location']


def test_indexed_predecessor_preserves_source_identity_and_rechecks_scope(monkeypatch):
    from services.tools import retrieval_tools
    local, get, parse, validate = fixture(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    def passage(index, text, owner='p', version='a' * 16):
        return {'text': text, 'metadata': {'id': owner, 'chunk_index': index,
            'index_version': version, 'section_title': 'Method', 'page': 5}}
    anchor = passage(16, 'where F maps images and camera matrices to Gaussian parameters.')
    previous = passage(15, 'Inputs include images and calibrated camera projection matrices.')
    rag = Mock()
    rag.normalize_id.side_effect = lambda value: value
    rag.get_documents_by_metadata.return_value = [previous,
        passage(15, 'Foreign paper.', owner='foreign'),
        passage(15, 'Other version.', version='b' * 16)]
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: rag)
    retrieve = Mock(return_value=[anchor])
    monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', retrieve)
    found = local('camera inputs', 'p', limit=2)
    assert len(found) == 2
    assert [row['chunkIndex'] for row in found] == [15, 16]
    assert found[0]['text'] == previous['text']
    assert found[1]['text'] == anchor['text']
    assert found[0]['sourceId'] != found[1]['sourceId']
    assert found[0]['contextForSourceId'] == found[1]['sourceId']
    assert found[0]['location']['page'] == 5
    retrieve.assert_called_with('camera inputs', top_k=8, filter_metadata={'id': 'p'}, allow_query_rewrite=False)
    assert local('camera inputs', 'p', limit=2) == found
    rag.get_documents_by_metadata.assert_called_once_with({'id': 'p'}, limit=400)
    validate.return_value = False
    with pytest.raises(DeepResearchError):
        local('camera inputs', 'p', limit=2)
    get.assert_not_called()
    parse.assert_not_called()


def test_indexed_named_row_is_retrieved_with_owner_version_and_cache_guards(monkeypatch):
    from services.tools import retrieval_tools
    local, get, parse, validate = fixture(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    def document(index, text, owner='p', version='a'*16):
        return {'text': text, 'metadata': {'id': owner, 'chunk_index': index,
            'index_version': version, 'section_title': 'Evaluation', 'page': 4}}
    top = document(0, 'Relevant method and dataset overview.')
    low = document(1, 'Generic benchmark overview.')
    literal = 'Table caption: Synthetic dataset.\nTable row 2: Hotdog | 0.2 | 30'
    named = document(2, literal)
    rag = Mock()
    rag.normalize_id.side_effect = lambda value: value
    rag.get_documents_by_metadata.return_value = [named, document(3,literal,owner='foreign'),
                                                 document(4,literal,version='b'*16)]
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: rag)
    monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', Mock(return_value=[top,low]))
    found = local('hotdog scene selection', 'p', limit=2)
    assert [r['chunkIndex'] for r in found] == [0,2]
    assert found[1]['text'] == literal and found[1]['retrievalMode'] == 'indexed_requested_row'
    assert found[1]['tableData'] is None  # Literal name retrieval grants no numeric approval.
    assert local('hotdog scene selection','p',limit=2) == found
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    get.assert_not_called()
    parse.assert_not_called()


def test_metric_retrieval_adds_owned_verified_tables_without_more_model_calls(monkeypatch):
    import json
    from services.tools import retrieval_tools
    local, get, parse, validate = fixture(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    prose = [{'text': f'Experimental results and evaluation protocol {i}.',
              'metadata': {'id': 'p', 'chunk_index': i, 'section_title': f'Section {i}'}} for i in range(5)]
    def table(owner, chunk, method, value):
        return {'text': f'Table row 1: {method} | {value} | 45MB', 'metadata': {
            'id': owner, 'chunk_index': chunk, 'table_id': 't1', 'page': 8,
            'table_verified_data': json.dumps({'groups': [['Scenes', ['FPS', 'Size']]],
                'rows': [[1, method, [value, '45MB']]]})}}
    rag = Mock()
    rag.normalize_id.side_effect = lambda value: value
    invalid = table('p', 12, 'Broken', '500')
    invalid['text'] = 'Truncated unrelated text.'
    rag.get_documents_by_metadata.return_value = [table('p', 10, 'Baseline', '120'),
        table('p', 11, 'Ours', '230'), table('foreign', 99, 'Ours', '999'), invalid]
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: rag)
    retrieve = Mock(return_value=prose)
    monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', retrieve)
    found = local('storage FPS experimental results', 'p', limit=5)
    assert len(found) == 5
    assert [row['chunkIndex'] for row in found] == [0, 11, 10, 1, 2]
    assert len({row['sourceId'] for row in found}) == 5
    assert all(row['pdfId'] == 'p' for row in found)
    assert found[1]['tableData']['rows'][0][1] == 'Ours'
    rag.get_documents_by_metadata.assert_called_once_with({'id': 'p'}, limit=400)
    assert len(local('FPS', 'p', limit=2)) == 2
    assert rag.get_documents_by_metadata.call_count == 1
    retrieve.assert_called_with('FPS', top_k=8, filter_metadata={'id': 'p'}, allow_query_rewrite=False)
    get.assert_not_called()
    parse.assert_not_called()
    validate.return_value = False
    with pytest.raises(DeepResearchError):
        local('FPS', 'p')


@pytest.mark.parametrize('marked', [True, False])
def test_component_detail_selection_uses_the_existing_index_cache_and_live_scope(monkeypatch, marked):
    from services.tools import retrieval_tools
    local, get, parse, validate = fixture(monkeypatch)
    if marked:
        local.repo.require_run.return_value['sourcePrecisionContractVersion'] = 1
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    def document(index, text, owner='p'):
        return {'text': text, 'metadata': {'id': owner, 'chunk_index': index,
            'index_version': 'a'*16, 'section_title': 'Method', 'page': 4}}
    top = document(0, 'TMC method overview using a previous representation.')
    low = document(1, 'Generic method overview.')
    previous = document(11, 'TMC encodes previous positions.')
    details = document(12, 'This maps TMC encoding to seven output dimensions: translation and rotation.')
    rag = Mock()
    rag.normalize_id.side_effect = lambda value: value
    rag.get_documents_by_metadata.return_value = [previous, details,
        document(12, 'Foreign TMC output dimensions and offsets.', owner='foreign')]
    monkeypatch.setattr(retrieval_tools, 'get_rag', lambda: rag)
    retrieve = Mock(return_value=[top,low])
    monkeypatch.setattr(retrieval_tools, 'retrieve_fused_evidence', retrieve)
    query = 'TMC prediction parameters'
    found = local(query,'p',limit=3)
    assert [r['chunkIndex'] for r in found] == ([0,11,12] if marked else [0,1])
    assert local(query,'p',limit=3) == found
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    assert all(r['pdfId'] == 'p' for r in found)
    if marked:
        assert found[1]['text'] == previous['text'] and found[2]['text'] == details['text']
        assert found[1]['contextForSourceId'] == found[2]['sourceId']
    validate.return_value = False
    with pytest.raises(DeepResearchError):
        local(query,'p',limit=3)
    assert retrieve.call_count == 2
    get.assert_not_called()
    parse.assert_not_called()


@pytest.mark.parametrize('version', [1, 2])
def test_requested_measurement_is_retrieved_from_owned_index_only_under_version_two(monkeypatch, version):
    from services.tools import retrieval_tools
    local, get, parse, validate = fixture(monkeypatch)
    local.repo.require_run.return_value['sourcePrecisionContractVersion'] = version
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec', lambda name: object())
    def document(index,text,owner='p'):
        return {'text':text,'metadata':{'id':owner,'chunk_index':index,'index_version':'a'*16,
            'section_title':'Results','page':4}}
    top=document(10,'Training about 15s per frame and rendering 140FPS.')
    low=document(11,'General benchmark overview.')
    exact=document(0,'Reconstruction takes 17 seconds and rendering reaches 140 FPS.')
    rag=Mock(); rag.normalize_id.side_effect=lambda value:value
    rag.get_documents_by_metadata.return_value=[exact,document(0,'17s and 140FPS',owner='foreign')]
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    retrieve=Mock(return_value=[top,low])
    monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    found=local('17 seconds per frame 140 FPS','p',limit=2)
    assert [r['chunkIndex'] for r in found] == ([10,0] if version==2 else [10,11])
    assert local('17 seconds per frame 140 FPS','p',limit=2) == found
    if version==2:
        assert found[1]['text']==exact['text'] and found[1]['retrievalMode']=='indexed_requested_measurement'
    rag.get_documents_by_metadata.assert_called_once_with({'id':'p'},limit=400)
    validate.return_value=False
    with pytest.raises(DeepResearchError):local('17 seconds per frame 140 FPS','p',limit=2)
    get.assert_not_called(); parse.assert_not_called()


def test_table_supplement_ignores_unrelated_metrics_and_deduplicates():
    from services.deep_research.local_sources import _include_metric_tables, _requested_metrics
    table = {'sourceId': 't', 'text': 'FPS results', 'tableData': {
        'groups': [['Scenes', ['FPS']]], 'rows': [[1, 'Ours', ['30']]]}}
    prose = {'sourceId': 'p', 'text': 'Evaluation protocol'}
    assert not _requested_metrics('explain the architecture')
    assert _include_metric_tables([prose], [table], 'SSIM', {'SSIM'}, 5) == [prose]
    chosen = _include_metric_tables([prose, table], [table], 'FPS', {'FPS'}, 5)
    assert chosen == [prose, table]


def test_foreign_material_never_constructs_file_request(monkeypatch):
    local, get, _, _ = fixture(monkeypatch, valid=False)
    with pytest.raises(DeepResearchError):
        local('pruning', 'foreign')
    get.assert_not_called()


def test_local_pdf_limit_stops_stream_before_parsing(monkeypatch):
    local, _, parse, _ = fixture(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.MAX_LOCAL_PDF_BYTES', 16)
    with pytest.raises(DeepResearchError, match='大小上限'):
        local('pruning', 'p')
    parse.assert_not_called()


def test_actual_parser_worker_accepts_the_parent_local_limit():
    import io
    from PyPDF2 import PdfWriter
    from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
    from services.deep_research.local_sources import _parse_pdf
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    page = writer.pages[0]
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 10 100 Td (Real parser evidence.) Tj ET')
    page[NameObject('/Contents')] = stream
    output = io.BytesIO()
    writer.write(output)
    pages = _parse_pdf(output.getvalue())
    assert pages[0]['page'] == 1 and 'Real parser evidence.' in pages[0]['text']
