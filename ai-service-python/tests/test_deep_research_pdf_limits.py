import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.config import Settings
from services.deep_research.external import AcademicAcquisition
from services.deep_research_academic import AcademicAccessError, AcademicPolicy, AcademicSourceClient


def test_public_pdf_limit_is_server_configurable_with_a_hard_ceiling(monkeypatch):
    monkeypatch.delenv('DEEP_RESEARCH_MAX_PDF_BYTES', raising=False)
    assert Settings(_env_file=None).deep_research_max_pdf_bytes == AcademicPolicy().max_pdf_bytes == 32 * 1024 * 1024
    for value in [0, 64 * 1024 * 1024 + 1]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, deep_research_max_pdf_bytes=value)
    monkeypatch.setenv('DEEP_RESEARCH_MAX_PDF_BYTES', str(16 * 1024 * 1024))
    configured = Settings(_env_file=None)
    monkeypatch.setattr('core.config.settings', configured)
    client = AcademicAcquisition(None, None)._client({'sourcePolicy': {'mode': 'academic_external'},
        'maxPdfBytes': 1024**4})  # A request cannot override server configuration.
    assert client.policy.max_pdf_bytes == 16 * 1024 * 1024


def test_illustrated_pdf_over_previous_limit_is_bounded_and_parsed_once(monkeypatch):
    from services import deep_research_academic as academic
    body = b'%PDF-' + b'x' * (9 * 1024 * 1024)
    calls = []
    def transport(host, path, maximum):
        calls.append(('download', maximum))
        return 'application/pdf', body
    def parse(args, **kwargs):
        calls.append(('parse', args, kwargs['timeout']))
        assert kwargs['input'] == body
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'page': 1, 'text': 'Source text.'}]).encode())
    monkeypatch.setattr(academic.subprocess, 'run', parse)
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external', allow_fulltext=True), transport)
    source = client.fetch_fulltext('2401.00001v2')
    assert source['accessLevel'] == 'fulltext' and source['versionId'] == 'arxiv:2401.00001v2'
    assert len(calls) == 2 and calls[0] == ('download', 32 * 1024 * 1024)
    assert calls[1][1][-2:] == ['100', str(32 * 1024 * 1024)] and calls[1][2] == 20


def test_actual_oversized_body_still_fails_before_parser_and_does_not_retry(monkeypatch):
    from services import deep_research_academic as academic
    parse = []
    monkeypatch.setattr(academic.subprocess, 'run', lambda *a, **k: parse.append(a))
    downloads = []
    def transport(*args):
        downloads.append(args)
        return 'application/pdf', b'%PDF-' + b'x' * 1024
    client = AcademicSourceClient(AcademicPolicy(enabled=True, mode='academic_external',
        allow_fulltext=True, max_pdf_bytes=1024), transport)
    with pytest.raises(AcademicAccessError, match='大小'):
        client.fetch_fulltext('2401.00001v2')
    assert len(downloads) == 1 and not parse
