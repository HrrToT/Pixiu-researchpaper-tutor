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
