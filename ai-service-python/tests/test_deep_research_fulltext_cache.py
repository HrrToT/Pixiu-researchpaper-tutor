from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from services.deep_research_academic import AcademicAccessError, AcademicPolicy, AcademicSourceClient
from services.deep_research.fulltext_cache import manifest_path, read_cached_fulltext, store_fulltext

BODY = b'%PDF-controlled-public-fixture'
ARXIV = '2312.12337v4'
POLICY = AcademicPolicy(enabled=True, mode='academic_external', allow_fulltext=True)


def fixture_client(tmp_path, monkeypatch, *, policy=POLICY, body=BODY):
    downloads, parses = [], []
    def transport(*args):
        downloads.append(args)
        return 'application/pdf', body
    def parse(args, **kwargs):
        parses.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'[{"page":1,"text":"Exact parsed source."}]')
    monkeypatch.setattr('services.deep_research_academic.subprocess.run', parse)
    return AcademicSourceClient(policy, transport, cache_dir=tmp_path), downloads, parses


def test_second_client_reuses_exact_revision_bytes_but_reparses_under_current_limits(tmp_path, monkeypatch):
    first, downloads, parses = fixture_client(tmp_path, monkeypatch)
    original = first.fetch_fulltext(ARXIV)
    assert not original['cacheHit'] and original['networkRequests'] == 1
    second = AcademicSourceClient(replace(POLICY, max_pages=7, parse_seconds=3),
        lambda *args: pytest.fail('Cache hit must not issue a provider request'), cache_dir=tmp_path)
    result = second.fetch_fulltext(ARXIV)
    assert result['cacheHit'] and result['cacheStatus'] == 'hit' and result['networkRequests'] == 0
    assert result['workId'] == original['workId'] and result['versionId'] == original['versionId']
    assert result['contentHash'] == hashlib.sha256(BODY).hexdigest()
    assert result['retrievedAt'] == original['retrievedAt'] and result['accessedAt'] >= original['retrievedAt']
    assert result['pages'] == original['pages']
    assert len(downloads) == 1 and len(parses) == 2
    assert parses[-1][0][-2:] == ['7', str(POLICY.max_pdf_bytes)] and parses[-1][1]['timeout'] == 3
    assert parses[-1][1]['input'] == BODY


@pytest.mark.parametrize('policy', [AcademicPolicy(), replace(POLICY, mode='task_only'), replace(POLICY, allow_fulltext=False)])
def test_cached_pdf_cannot_bypass_current_source_or_fulltext_permission(tmp_path, monkeypatch, policy):
    first, _, _ = fixture_client(tmp_path, monkeypatch)
    first.fetch_fulltext(ARXIV)
    client, downloads, parses = fixture_client(tmp_path, monkeypatch, policy=policy)
    monkeypatch.setattr('services.deep_research.fulltext_cache.read_cached_fulltext',
        lambda *args: pytest.fail('Policy rejection must precede even cache lookup'))
    with pytest.raises(AcademicAccessError):
        client.fetch_fulltext(ARXIV)
    assert not downloads and not parses


def test_unversioned_or_different_revision_never_reuses_a_prior_version(tmp_path, monkeypatch):
    client, downloads, parses = fixture_client(tmp_path, monkeypatch)
    client.fetch_fulltext(ARXIV)
    for identity in ['2312.12337v5', '2312.12337', '2312.12337']:
        result = client.fetch_fulltext(identity)
        assert not result['cacheHit'] and result['networkRequests'] == 1
        assert result['versionId'] == 'arxiv:' + identity
    assert len(downloads) == len(parses) == 4
    assert manifest_path(tmp_path, '2312.12337') is None


@pytest.mark.parametrize('change', ['bad_json', 'oversized_manifest', 'other_version', 'traversal_hash',
    'wrong_digest', 'missing_pdf', 'changed_pdf', 'non_pdf', 'nan_timestamp', 'bool_timestamp', 'bool_version'])
def test_invalid_cache_is_a_miss_followed_by_only_one_fresh_request(tmp_path, monkeypatch, change):
    client, downloads, parses = fixture_client(tmp_path, monkeypatch)
    result = client.fetch_fulltext(ARXIV)
    index = manifest_path(tmp_path, ARXIV)
    record = json.loads(index.read_text())
    pdf = tmp_path / (result['contentHash'] + '.pdf')
    if change == 'bad_json': index.write_text('not json')
    elif change == 'oversized_manifest': index.write_text(' ' * 5000)
    elif change == 'other_version': record['arxivId'] = '2312.12337v5'
    elif change == 'traversal_hash': record['contentHash'] = '../../outside'
    elif change == 'wrong_digest': record['contentHash'] = '0' * 64
    elif change == 'missing_pdf': pdf.unlink()
    elif change == 'changed_pdf': pdf.write_bytes(BODY + b'changed')
    elif change == 'non_pdf': pdf.write_bytes(b'not PDF')
    elif change == 'nan_timestamp': record['retrievedAt'] = float('nan')
    elif change == 'bool_timestamp': record['retrievedAt'] = True
    elif change == 'bool_version': record['version'] = True
    if change not in {'bad_json', 'oversized_manifest'}:
        index.write_text(json.dumps(record))
    fresh = client.fetch_fulltext(ARXIV)
    assert not fresh['cacheHit'] and fresh['networkRequests'] == 1
    assert len(downloads) == len(parses) == 2
    assert read_cached_fulltext(tmp_path, ARXIV, POLICY.max_pdf_bytes)['body'] == BODY


def test_smaller_current_byte_limit_cannot_accept_an_older_larger_cache(tmp_path, monkeypatch):
    client, _, _ = fixture_client(tmp_path, monkeypatch)
    client.fetch_fulltext(ARXIV)
    limited, downloads, parses = fixture_client(tmp_path, monkeypatch, policy=replace(POLICY, max_pdf_bytes=10))
    with pytest.raises(AcademicAccessError, match='大小'):
        limited.fetch_fulltext(ARXIV)
    assert len(downloads) == 1 and not parses


def test_cached_parser_failure_does_not_download_or_retry(tmp_path, monkeypatch):
    client, downloads, parses = fixture_client(tmp_path, monkeypatch)
    client.fetch_fulltext(ARXIV)
    monkeypatch.setattr('services.deep_research_academic.subprocess.run',
        lambda *a, **kw: SimpleNamespace(returncode=2, stdout=b''))
    with pytest.raises(AcademicAccessError, match='解析结果'):
        client.fetch_fulltext(ARXIV)
    assert len(downloads) == len(parses) == 1


def test_cache_write_failure_preserves_fresh_success_without_another_request(tmp_path, monkeypatch):
    client, downloads, parses = fixture_client(tmp_path, monkeypatch)
    def denied(*args): raise PermissionError('Fixture cache unavailable')
    monkeypatch.setattr('services.deep_research.fulltext_cache.store_fulltext', denied)
    result = client.fetch_fulltext(ARXIV)
    assert result['accessLevel'] == 'fulltext' and result['cacheStatus'] == 'write_failed'
    assert result['pages'][0]['text'] == 'Exact parsed source.'
    assert len(downloads) == len(parses) == 1


def test_old_style_arxiv_identity_uses_a_flat_hashed_index(tmp_path):
    assert store_fulltext(tmp_path, 'cs/0701001v2', BODY, 100, POLICY.max_pdf_bytes)
    index = manifest_path(tmp_path, 'cs/0701001v2')
    assert index.parent == tmp_path and index.is_file()
    assert read_cached_fulltext(tmp_path, 'cs/0701001v2', POLICY.max_pdf_bytes)['body'] == BODY
    with pytest.raises(ValueError):
        store_fulltext(tmp_path, '../secret', BODY, 100, POLICY.max_pdf_bytes)


def test_symlinked_index_is_not_followed_before_network_fallback(tmp_path, monkeypatch):
    client, downloads, parses = fixture_client(tmp_path, monkeypatch)
    client.fetch_fulltext(ARXIV)
    index = manifest_path(tmp_path, ARXIV)
    original = type(index).is_symlink
    monkeypatch.setattr(type(index), 'is_symlink', lambda path: path == index or original(path))
    client.fetch_fulltext(ARXIV)
    assert len(downloads) == len(parses) == 2


def test_cross_run_cache_hit_is_reserved_recorded_and_replayed_once(tmp_path, monkeypatch):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import ExternalAcademicAdapter
    client, downloads, parses = fixture_client(tmp_path / 'public', monkeypatch)
    repo = DeepResearchRepository(str(tmp_path / 'research.sqlite3'))
    repo.initialize()
    for run in ['first', 'second']:
        repo.create_run({'runId': run, 'taskId': 't', 'question': 'Public topic',
                         'sourcePolicy': {'mode': 'academic_external'}})
        repo.begin_execution(run)
    adapter = ExternalAcademicAdapter(client, repo.reserve_call, repo.complete_call)
    original = adapter.fetch_fulltext('first', ARXIV)
    cached = adapter.fetch_fulltext('second', ARXIV)
    assert not original['cacheHit'] and cached['cacheHit'] and cached['networkRequests'] == 0
    assert adapter.fetch_fulltext('second', ARXIV) == cached
    assert len(downloads) == 1 and len(parses) == 2
    for run in ['first', 'second']:
        assert repo.require_run(run)['budget']['fulltextFetches'] == 1
        rows = repo.list_calls(run)
        assert len(rows) == 1 and rows[0]['status'] == 'succeeded'
    assert repo.list_calls('second')[0]['result']['cacheHit'] is True
