"""Bind new local prose evidence to the physical pages of its frozen PDF."""
import subprocess
import requests
from contextlib import contextmanager
from time import monotonic
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import make_evidence


def located_evidence_factory(repo, run_id, local, *, cache_failed_batches=False):
    if type(cache_failed_batches) is not bool:raise ValueError('Invalid page failure reuse policy')
    # LocalTaskRetriever owns the per-run PDF cache. Nothing is written back to
    # historical sources/reports, and evidence identity includes the new location.
    batch_pages = None
    batch_diagnostics = None
    last_diagnostics = None
    failed_pages = set()

    @contextmanager
    def physical_page_batch():
        """Only for a local extraction bracketed by live scope validation."""
        nonlocal batch_pages, batch_diagnostics, last_diagnostics
        if batch_pages is not None:
            raise DeepResearchError('invalid_page_batch', '不能嵌套正文页码回查批次。')
        batch_pages = {}
        failed_pages.clear()
        from services.deep_research.page_diagnostics import PageDiagnostics
        batch_diagnostics = PageDiagnostics()
        try:
            yield
        finally:
            # A later read or provider send cannot inherit this permission window.
            batch_pages = None
            failed_pages.clear()
            last_diagnostics = batch_diagnostics.snapshot()
            batch_diagnostics = None

    def create(source, quote, original, *, location, obligation_ids, conditions=None):
        from services.deep_research.quote_pages import resolve_quote_location
        audit=batch_diagnostics if batch_pages is not None else None
        started=monotonic()
        record = repo.require_run(run_id)
        if audit:
            audit.value['quotes']+=1
            audit.value['repositorySeconds']+=monotonic()-started
        material = next((m for m in record.get('materials', [])
                         if m.get('materialId') == source.get('workId')), None)
        if material and source.get('accessLevel') == 'fulltext':
            # Verified table rows are a parser serialization, not literal PDF
            # prose. Keep their existing geometric locator only when the exact
            # persisted source packet proves this is such a row.
            from services.deep_research.table_evidence import visible_table_packet
            table_row = False
            for item in record.get('state', {}).get('sources', []):
                if (item.get('workId') != source.get('workId') or
                        item.get('contentHash') != source.get('contentHash') or
                        item.get('versionId') != source.get('versionId')):
                    continue
                packet = visible_table_packet(item.get('tableData'), original)
                if packet:
                    table_row = any(quote == f'Table row {n}: ' + ' | '.join([method, *values])
                                    for n, method, values in packet['rows'])
                if table_row:
                    break
            if not table_row:
                key = (material['materialId'], material.get('contentHash'))
                try:
                    if batch_pages is not None and key in batch_pages:
                        pages = batch_pages[key]
                        if audit:audit.value['cacheHits']+=1
                        if audit and key in failed_pages:audit.value['failedCacheHits']+=1
                    else:
                        started=monotonic()
                        if audit:audit.value['loads']+=1
                        try:
                            _, pages = local.load_pages(source['workId'])
                        finally:
                            if audit:audit.value['loadSeconds']+=monotonic()-started
                        if batch_pages is not None and pages:
                            batch_pages[key] = pages
                except DeepResearchError as exc:
                    if audit:audit.failure(exc)
                    if exc.code in {'scope_revoked', 'source_changed', 'source_missing'}:
                        raise
                    # A transient file/parse failure must never endorse the old
                    # section page. Evidence text is still checked independently.
                    pages = []
                    if cache_failed_batches and batch_pages is not None and exc.code=='source_parse_failed':
                        batch_pages[key]=[]
                        failed_pages.add(key)
                except (requests.RequestException, subprocess.TimeoutExpired) as exc:
                    if audit:audit.failure(exc)
                    pages = []
                started=monotonic()
                location = resolve_quote_location(quote, pages, location)
                if audit:audit.value['resolveSeconds']+=monotonic()-started
        if audit:audit.resolution(location)
        return make_evidence(source, quote, original, location=location,
                             obligation_ids=obligation_ids, conditions=conditions)
    create.physical_page_batch = physical_page_batch
    def diagnostics():
        from copy import deepcopy
        return batch_diagnostics.snapshot() if batch_diagnostics else deepcopy(last_diagnostics)
    create.physical_page_diagnostics = diagnostics
    return create
