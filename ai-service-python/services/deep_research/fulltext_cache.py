"""Content-addressed public PDFs; only explicit arXiv revisions may be reused."""
import hashlib
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4


def manifest_path(directory, arxiv_id):
    if not isinstance(arxiv_id, str) or not re.fullmatch(
            r'(?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z.-]+/\d{7})v[1-9]\d*', arxiv_id):
        return None
    return Path(directory) / ('arxiv-' + hashlib.sha256(arxiv_id.encode()).hexdigest() + '.json')


def _regular_file(path):
    return not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)() and path.is_file()


def _read_pdf(path, content_hash, maximum):
    if not _regular_file(path) or path.stat().st_size > maximum:
        return None
    with path.open('rb') as handle:
        body = handle.read(maximum + 1)
    if (len(body) > maximum or not body.startswith(b'%PDF-')
            or hashlib.sha256(body).hexdigest() != content_hash):
        return None
    return body


def read_cached_fulltext(directory, arxiv_id, maximum):
    """A miss performs no network request; caller still checks policy and parses."""
    if directory is None or type(maximum) is not int or not 1 <= maximum <= 64 * 1024 * 1024:
        return None
    index = manifest_path(directory, arxiv_id)
    if index is None:
        return None  # An unversioned lookup must check the remote latest version.
    try:
        if not _regular_file(index) or index.stat().st_size > 4096:
            return None
        with index.open('rb') as handle:
            encoded = handle.read(4097)
        if len(encoded) > 4096:
            return None
        record = json.loads(encoded.decode('utf-8'))
        if (not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1
                or record.get('arxivId') != arxiv_id
                or not isinstance(record.get('contentHash'), str)
                or re.fullmatch(r'[0-9a-f]{64}', record['contentHash']) is None
                or type(record.get('retrievedAt')) not in (int, float)
                or not math.isfinite(record['retrievedAt'])
                or not 0 < record['retrievedAt'] <= time.time() + 5):
            return None
        body = _read_pdf(Path(directory) / (record['contentHash'] + '.pdf'), record['contentHash'], maximum)
        if body is None:
            return None
        return {'body': body, 'contentHash': record['contentHash'], 'retrievedAt': record['retrievedAt']}
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _atomic_write(path, body):
    temporary = path.parent / ('.' + path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(body)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def store_fulltext(directory, arxiv_id, body, retrieved_at, maximum):
    """Store only after parser success; bytes are checked again before indexing.

    Caller owns the arXiv/download association. A manifest contains no paths,
    page text or model output. Unversioned PDFs remain available to the reader,
    but get no reusable revision index.
    """
    if (not isinstance(arxiv_id, str) or re.fullmatch(
            r'(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7})(?:v[1-9]\d*)?', arxiv_id, re.I) is None
            or type(maximum) is not int or not 1 <= maximum <= 64 * 1024 * 1024
            or not isinstance(body, bytes) or len(body) > maximum or not body.startswith(b'%PDF-')
            or type(retrieved_at) not in (int, float) or not math.isfinite(retrieved_at)
            or not 0 < retrieved_at <= time.time() + 5):
        raise ValueError('Invalid public fulltext cache entry')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(body).hexdigest()
    target = directory / (content_hash + '.pdf')
    try:
        exists = _read_pdf(target, content_hash, maximum) is not None
    except OSError:
        exists = False
    if not exists:
        _atomic_write(target, body)
    index = manifest_path(directory, arxiv_id)
    if index is None:
        return False
    record = {'version': 1, 'arxivId': arxiv_id, 'contentHash': content_hash, 'retrievedAt': retrieved_at}
    _atomic_write(index, json.dumps(record, separators=(',', ':')).encode('utf-8'))
    return True
