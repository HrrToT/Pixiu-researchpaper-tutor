"""Bounded local PDF retrieval when the vector backend is unavailable."""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import requests

from services.deep_research.contracts import DeepResearchError

MAX_LOCAL_PDF_BYTES = 64 * 1024 * 1024

class LocalTaskRetriever:
    def __init__(self, repo, run_id, validate, *, origin, get=requests.get, parse=None):
        self.repo, self.run_id, self.validate = repo, run_id, validate
        self.origin, self.get = origin.rstrip('/'), get
        self.parse = parse
        self.pages = {}
        self.index_tables = {}
        self.index_context = {}
        self._page_locks = {}
        self._page_locks_guard = threading.Lock()
        self._measurement_read_lock = threading.RLock()
        self._measurement_read_failures = {}
        self._publication_identity_lock = threading.RLock()
        self._publication_identities = {}

    def __call__(self, query, pdf_id, *, limit=5):
        if not self.validate(self.run_id, pdf_id):
            raise DeepResearchError("scope_revoked", "论文范围已变更")
        indexed_for_pdf = None
        # Keep the existing indexed route where its runtime is installed.
        if importlib.util.find_spec('sentence_transformers') is not None:
            try:
                from services.research_executor import retrieve_current_paper_evidence
                items = retrieve_current_paper_evidence(query, pdf_id, limit=limit, allow_query_rewrite=False)
                if items:
                    from services.tools.retrieval_tools import get_rag
                    rag = get_rag()
                    owned = rag.normalize_id(pdf_id)
                    # The backend's filter is not proof of document ownership.
                    items = [item for item in items if (item.get('metadata') or {}).get('id') == owned]
                if items:
                    indexed = [_indexed_source(item) for item in items]
                    if limit > 1:
                        from services.evidence_service import normalize_evidence_items
                        from services.deep_research.named_source_rows import include_requested_rows
                        from services.deep_research.source_continuity import needs_preceding_context, include_preceding_context
                        if pdf_id not in self.index_context:
                            raw = rag.get_documents_by_metadata({'id': owned}, limit=400)
                            # Recheck owner even if the backend ignores its filter.
                            raw = [row for row in raw if row.get('metadata', {}).get('id') == owned]
                            normalized = normalize_evidence_items(raw, source_type='current_paper',
                                pdf_id=owned, max_text_chars=2000)
                            self.index_context[pdf_id] = [_indexed_source(row) for row in normalized]
                        from services.deep_research.mechanism_sources import for_query as qualitative_query
                        metrics = set() if qualitative_query(self.repo.require_run(self.run_id),query,pdf_id) else _requested_metrics(query)
                        if metrics:
                            self.index_tables[pdf_id] = [row for row in self.index_context[pdf_id] if row.get('tableData')]
                            indexed = _include_metric_tables(indexed, self.index_tables[pdf_id], query, metrics, limit)
                        elif any(needs_preceding_context(row) for row in indexed):
                            indexed = include_preceding_context(indexed, self.index_context[pdf_id], owned, limit)
                        from services.deep_research.method_details import enabled as precise_sources, include_method_details
                        precision_record=self.repo.require_run(self.run_id)
                        if not metrics and type(precision_record.get('sourcePrecisionContractVersion')) is int and precision_record['sourcePrecisionContractVersion'] in (6,7,8):
                            from services.deep_research.criterion_sources import acquisition_questions,include_indexed_criteria,acquisition_modules,acquisition_conditions
                            questions=acquisition_questions(precision_record,query,owned)
                            indexed=include_indexed_criteria(indexed,self.index_context[pdf_id],questions,owned,limit,
                                supervision=precision_record.get('comparisonSupervisionPremisesVersion') == 1,
                                compression_operations=(precision_record.get('comparisonMechanismReadContractVersion', 0)
                                    if precision_record.get('comparisonMechanismReadContractVersion') in (2, 3, 4, 5, 6) else False),
                                **({'modules':acquisition_modules(precision_record,query,owned)}
                                   if precision_record['sourcePrecisionContractVersion'] in (7,8) else {}),
                                **({'conditions':acquisition_conditions(precision_record,query,owned)}
                                   if precision_record['sourcePrecisionContractVersion']==8 else {}))
                        elif not metrics and precise_sources(precision_record):
                            indexed = include_method_details(indexed, self.index_context[pdf_id], query, owned, limit,
                                semantic_intent=self.repo.require_run(self.run_id).get('sourcePrecisionContractVersion') in (4,5),
                                **({'operational_intent':True} if self.repo.require_run(self.run_id).get('sourcePrecisionContractVersion')==5 else {}))
                        precision = self.repo.require_run(self.run_id).get('sourcePrecisionContractVersion')
                        if type(precision) is int and precision in (2, 3, 4, 5, 6, 7, 8):
                            from services.deep_research.requested_measurements import include_requested_measurements
                            indexed = include_requested_measurements(indexed, self.index_context[pdf_id], query, owned, limit)
                        from services.deep_research.requested_table_rows import enabled as named_identity, human_row_question
                        row_record = self.repo.require_run(self.run_id)
                        symbolic_rows = named_identity(row_record)
                        row_question = human_row_question(row_record) if symbolic_rows else query
                        indexed = include_requested_rows(indexed, self.index_context[pdf_id], row_question, owned, limit,
                                                         symbol_identity=symbolic_rows)
                        from services.deep_research.source_continuity import enabled as continuity_enabled,method_enabled,include_method_context
                        if not metrics and continuity_enabled(precision_record):
                            # Apply after criterion/method/row selection so the
                            # context is not displaced by a later selector.
                            indexed = include_preceding_context(indexed, self.index_context[pdf_id], owned, limit,
                                illustrative=True)
                            if method_enabled(precision_record):
                                indexed = include_method_context(indexed,self.index_context[pdf_id],owned,limit)
                    if limit > 1 and type(precision) is int and precision in (3,4,5,6,7,8):
                        indexed_for_pdf = indexed
                    else:
                        return self._stamp_identity(self._scope_evidence(indexed,self.index_context.get(pdf_id,[]),query,pdf_id,limit), pdf_id)
            except (ImportError, RuntimeError, OSError):
                pass
        if indexed_for_pdf is not None:
            # Keep optional PDF read failures outside the index-backend
            # fallback catch; a programming error must not trigger a second GET.
            indexed=self._supplement_pdf_measurements(indexed_for_pdf, query, pdf_id, limit)
            found = self._scope_evidence(indexed, self.index_context.get(pdf_id, []), query, pdf_id, limit)
            return self._stamp_identity(self._experiment_protocol_passages(found, query, pdf_id, limit), pdf_id)
        material, pages = self.load_pages(pdf_id)
        record = self.repo.require_run(self.run_id)
        passages = self._pdf_passages(pdf_id, material, pages, record=record)
        scores = _bm25(query, [value['text'] for value in passages])
        ranked = sorted(zip(scores, passages), key=lambda value: -value[0])
        found = [value for score, value in ranked[:min(max(int(limit), 0), 5)] if score > 0]
        if record.get('namedTablePdfFallbackVersion') == 1 and limit > 0:
            from services.deep_research.named_table_scope import requested_number, requested_row_numbers
            from services.deep_research.request_context import effective_question
            question = effective_question(record)
            number = requested_number(question)
            matching = [row for row in passages if row.get('tableData') and number
                        and row['location'].get('section') == f'Table {number}'
                        and requested_row_numbers(row['tableData'], question,
                                                  grouped_rows=record.get('namedTableGroupedRowsVersion') == 1)]
            if len(matching) == 1:
                table, = matching
                found = [table, *(row for row in found if row['sourceId'] != table['sourceId'])][:min(limit, 5)]
        if record.get('comparisonPdfTableFallbackVersion') in (1, 2) and limit >= 2:
            metrics = _requested_metrics(query)
            if not metrics and re.search(r'\bbaseline\b|基线', query, re.I) and re.search(r'\bbenchmark\b|对照', query, re.I):
                metrics = {'FPS', 'SIZE', 'PSNR', 'SSIM', 'LPIPS'}
            if metrics:
                found = _include_metric_tables(found, [row for row in passages if row.get('tableData')],
                                               query, metrics, min(limit, 5),
                                               marked_headers=record.get('comparisonBenchmarkSpeedScopeContractVersion') == 7)
        precision = record.get('sourcePrecisionContractVersion')
        if type(precision) is int and precision in (3,4,5,6,7,8):
            from services.deep_research.requested_measurements import include_pdf_measurements
            if not self.validate(self.run_id,pdf_id):
                raise DeepResearchError('scope_revoked','论文范围已变更')
            passages = [{**row,'versionId':material.get('versionId') or material['contentHash']} for row in passages]
            found = include_pdf_measurements(found,passages,query,pdf_id,material['contentHash'],min(limit,5))
        if type(precision) is int and precision in (6,7,8):
            from services.deep_research.criterion_sources import acquisition_questions,include_pdf_criteria,acquisition_modules,acquisition_conditions
            questions=acquisition_questions(self.repo.require_run(self.run_id),query,pdf_id)
            found=include_pdf_criteria(found,passages,questions,pdf_id,material['contentHash'],min(limit,5),
                supervision=record.get('comparisonSupervisionPremisesVersion') == 1,
                compression_operations=(record.get('comparisonMechanismReadContractVersion', 0)
                    if record.get('comparisonMechanismReadContractVersion') in (2, 3, 4, 5, 6) else False),
                **({'modules':acquisition_modules(self.repo.require_run(self.run_id),query,pdf_id)} if precision in (7,8) else {}),
                **({'conditions':acquisition_conditions(self.repo.require_run(self.run_id),query,pdf_id)} if precision==8 else {}))
        found = self._scope_evidence(found, passages, query, pdf_id, limit)
        from services.deep_research.section_context import include_pdf_method_heading, include_pdf_method_passages
        found = include_pdf_method_heading(found, pages, record, query, material, min(limit, 5))
        found = include_pdf_method_passages(found, pages, record, query, material, min(limit, 5))
        from services.deep_research.measurement_table_navigation import retain_threshold_table
        benchmarks = self._threshold_benchmarks(record, query)
        found = retain_threshold_table(found, passages, benchmarks, min(limit, 5))
        if record.get('comparisonNamedBenchmarkProtocolVersion') in (1, 2):
            from services.deep_research.pdf_benchmark_protocol import include_protocol
            found = include_protocol(found, pages, material, benchmarks, min(limit, 5),
                include_metric_definition=record.get('comparisonNamedBenchmarkProtocolVersion') == 2)
        from services.deep_research.mechanism_sources import include_pdf_representation, representation_read_requested
        if limit >= 2 and representation_read_requested(record, query, pdf_id):
            found = include_pdf_representation(found, pages, material, min(limit, 5))
        if _read_runtime_tradeoff(record, query):
            from services.deep_research.runtime_evidence import include_pdf_tradeoff
            found = include_pdf_tradeoff(found, passages, min(limit, 5))
        return self._stamp_identity(
            self._experiment_protocol_passages(found, query, pdf_id, min(limit, 5), passages=passages,
                                               pages=pages, material=material), pdf_id)

    def _experiment_protocol_passages(self, rows, query, pdf_id, limit, *, passages=None, pages=None, material=None):
        from services.deep_research import experiment_protocol_sources as protocol

        record = self.repo.require_run(self.run_id)
        if limit < 2 or not protocol.enabled(record):
            return rows
        roles = protocol.query_roles(record, query, pdf_id)
        missing_roles = any(not protocol.has_passage(rows, role) for role in roles)
        baseline = protocol.baseline_evaluation_requested(record, query, pdf_id) if limit >= 3 else None
        if not missing_roles and not baseline:
            return rows
        if (missing_roles and passages is None) or (baseline and pages is None):
            try:
                material, pages = self.load_pages(pdf_id)
            except DeepResearchError as error:
                if (error.code not in {'source_unavailable', 'source_too_large', 'source_parse_failed'}
                        or error.details.get('status_code') in {401, 403}):
                    raise
                return rows
            except (requests.RequestException, subprocess.TimeoutExpired):
                return rows
            if missing_roles and passages is None:
                passages = self._pdf_passages(pdf_id, material, pages, record=record)
        if not self.validate(self.run_id, pdf_id):
            raise DeepResearchError('scope_revoked', '论文范围已变更')
        if missing_roles:
            rows = protocol.include_passages(rows, passages, roles, limit)
        if baseline:
            rows = protocol.retain_baseline_evaluation(
                rows, protocol.baseline_evaluation_passages(pages, material, baseline), limit)
        return rows

    @staticmethod
    def _threshold_benchmarks(record, query):
        if record.get('comparisonThresholdTablePdfFallbackVersion') != 1:
            return set()
        from services.deep_research.measurement_table_navigation import requested_threshold_benchmarks
        from services.deep_research.named_benchmark_navigation import human_text

        return requested_threshold_benchmarks(human_text(record), query)


    def _scope_evidence(self,rows,candidates,query,pdf_id,limit):
        from services.deep_research.scope_evidence import enabled,include_scope_evidence
        record=self.repo.require_run(self.run_id)
        from services.deep_research.processing_cost_sources import include_processing_cost
        from services.deep_research.table_note_index import retain_local_protocol_note
        if not enabled(record):
            from services.deep_research.mechanism_sources import prefer_sources
            result=prefer_sources(rows,candidates,record,query,pdf_id,limit)
            result=include_processing_cost(result,candidates,record,query,pdf_id,limit)
            return retain_local_protocol_note(result,candidates,record,query,limit)
        if not self.validate(self.run_id,pdf_id):
            raise DeepResearchError('scope_revoked','论文范围已变更')
        material=next((m for m in record.get('materials',[]) if m.get('materialId')==pdf_id),{})
        result=include_scope_evidence(rows,candidates,record,query,pdf_id,limit,content_hash=material.get('contentHash'))
        from services.deep_research.table_identity_context import enabled as identity_context_enabled, include_context
        if identity_context_enabled(record):
            result=include_context(result,candidates,pdf_id,limit)
        if not self.validate(self.run_id,pdf_id):
            raise DeepResearchError('scope_revoked','论文范围已变更')
        from services.deep_research.mechanism_sources import prefer_sources
        result=prefer_sources(result,candidates,record,query,pdf_id,limit)
        from services.deep_research.named_benchmark_navigation import enabled as benchmark_navigation, include_named_benchmark_tables
        if benchmark_navigation(record):
            result=include_named_benchmark_tables(result,candidates,record,query,pdf_id,limit)
        from services.deep_research.section_context import include_section_context, include_explanation_method
        result=include_section_context(result,candidates,record,pdf_id,limit)
        result=include_explanation_method(result,candidates,record,query,pdf_id,limit)
        result=include_processing_cost(result,candidates,record,query,pdf_id,limit)
        from services.deep_research.named_table_scope import include_indexed_rows
        result=include_indexed_rows(result,candidates,record,pdf_id,limit)
        result=retain_local_protocol_note(result,candidates,record,query,limit)
        from services.deep_research.comparison_joint_reports import retain_evaluation_protocol
        return retain_evaluation_protocol(result,candidates,record,query,pdf_id,material.get('contentHash'),limit)


    def _stamp_identity(self, rows, pdf_id):
        record = self.repo.require_run(self.run_id)
        if not rows or type(record.get('sourcePrecisionContractVersion')) is not int or record['sourcePrecisionContractVersion'] not in (4,5,6,7,8):
            return rows
        if not self.validate(self.run_id,pdf_id):
            raise DeepResearchError('scope_revoked','论文范围已变更')
        material=next((m for m in record.get('materials',[]) if m.get('materialId')==pdf_id),None)
        if not material or not material.get('contentHash'):
            raise DeepResearchError('source_missing','论文版本未保存')
        key=(pdf_id,material['contentHash'])
        with self._publication_identity_lock:
            if key not in self._publication_identities:
                try:
                    material,pages=self.load_pages(pdf_id)
                    from services.deep_research.publication_identity import from_verified_pages
                    identity=from_verified_pages(material,pages)
                except DeepResearchError as exc:
                    if exc.code not in {'source_unavailable','source_too_large','source_parse_failed'} or exc.details.get('status_code') in {401,403}:
                        raise
                    identity=None
                except (requests.RequestException,subprocess.TimeoutExpired):
                    identity=None
                self._publication_identities[key]=identity
            identity=self._publication_identities[key]
        if not self.validate(self.run_id,pdf_id):
            raise DeepResearchError('scope_revoked','论文范围已变更')
        from copy import deepcopy
        return [{**row,'publicationIdentity':deepcopy(identity)} for row in rows] if identity else rows


    @staticmethod
    def _pdf_passages(pdf_id, material, pages, *, record=None):
        from services.deep_research.quote_context import _sentence_cuts

        align = (record or {}).get('comparisonPdfPassageBoundaryVersion') in (1, 2)
        passages = []
        for page in pages:
            text = page.get('text', '')
            cuts = _sentence_cuts(text) if align else []
            for nominal in range(0, len(text), 1500):
                offset = nominal
                cut_index = bisect_right(cuts, nominal)
                if cut_index and nominal - cuts[cut_index - 1] <= 150:
                    offset = cuts[cut_index - 1]
                passage = text[offset:offset + 1800]
                if passage.strip():
                    location = {'page': page['page'], 'offset': offset}
                    identity = hashlib.sha256(f"{pdf_id}:{material['contentHash']}:{location}".encode()).hexdigest()
                    passages.append({'sourceId': 'src_' + identity, 'pdfId': pdf_id, 'text': passage,
                        'location': location, 'contentHash': material['contentHash'], 'versionId': material.get('versionId'),
                        'title': material.get('title', pdf_id), 'accessLevel': 'fulltext', 'retrievalMode': 'pdf_lexical_fallback'})
            for table in page.get('verifiedTables', []):
                number, packet = table['number'], table['tableData']
                directions = table.get('metricDirections', ())
                if ((record or {}).get('comparisonBenchmarkSpeedScopeContractVersion') == 7
                        and len(directions) == sum(len(metrics) for _, metrics in packet['groups'])
                        and all(direction in ('↑', '↓') for direction in directions)):
                    arrows = iter(directions)
                    packet = {**packet, 'groups': [
                        [group, [metric + next(arrows) for metric in metrics]]
                        for group, metrics in packet['groups']
                    ]}
                header = ' | '.join(f'{group} / {metric}' for group, metrics in packet['groups'] for metric in metrics)
                lines = [f"Table caption: {table['caption']}", f'Table row 1: Method | {header}']
                lines.extend(f'Table row {n}: ' + ' | '.join([label, *values]) for n, label, values in packet['rows'])
                location = {'page': page['page'], 'pageIndex': page['page'] - 1, 'pageResolution': 'exact',
                            'section': f'Table {number}', 'table': f"pdf-page-{page['page']}-table-{number}",
                            'tableColumnMappingUnverified': False}
                if table.get('thresholdProjection') is True:
                    location['thresholdColumnsVerified'] = True
                identity = hashlib.sha256(f"{pdf_id}:{material['contentHash']}:{location}".encode()).hexdigest()
                passages.append({'sourceId': 'src_' + identity, 'pdfId': pdf_id, 'text': '\n'.join(lines),
                    'location': location, 'contentHash': material['contentHash'], 'versionId': material.get('versionId'),
                    'title': material.get('title', pdf_id), 'accessLevel': 'fulltext',
                    'retrievalMode': 'pdf_verified_table', 'tableData': packet})
        return passages


    def _supplement_pdf_measurements(self, indexed, query, pdf_id, limit):
        from services.deep_research.mechanism_sources import include_pdf_representation, representation_read_requested
        from services.deep_research.requested_measurements import missing_measurements, include_pdf_measurements, owned_measurement_sources
        # One owned PDF is parsed once, even when two local queries arrive
        # together. A known optional read failure is not repeatedly dispatched.
        with self._measurement_read_lock:
            if not self.validate(self.run_id,pdf_id):
                raise DeepResearchError('scope_revoked','论文范围已变更')
            record = self.repo.require_run(self.run_id)
            material = next((m for m in record.get('materials',[]) if m.get('materialId') == pdf_id),None)
            if not material or not material.get('contentHash'):
                raise DeepResearchError('source_missing','论文版本未保存')
            indexed = owned_measurement_sources(indexed,pdf_id,material['contentHash'])
            benchmarks = self._threshold_benchmarks(record, query)
            missing = missing_measurements(indexed,query)
            representation = representation_read_requested(record, query, pdf_id)
            runtime_tradeoff = _read_runtime_tradeoff(record, query)
            if limit < 2 or not (missing or benchmarks or representation or runtime_tradeoff):
                return indexed
            key = (pdf_id,material['contentHash'])
            failure = self._measurement_read_failures.get(key) if key not in self.pages else None
            if failure is None:
                try:
                    material,pages = self.load_pages(pdf_id)
                except DeepResearchError as exc:
                    if (exc.code not in {'source_unavailable','source_too_large','source_parse_failed'}
                            or exc.details.get('status_code') in {401,403}):
                        raise
                    failure = {'status':'unavailable','code':exc.code}
                except requests.RequestException:
                    failure = {'status':'unavailable','code':'source_unavailable'}
                except subprocess.TimeoutExpired:
                    failure = {'status':'unavailable','code':'source_parse_timeout'}
                if failure:
                    self._measurement_read_failures[key] = failure
            if not self.validate(self.run_id,pdf_id):
                raise DeepResearchError('scope_revoked','论文范围已变更')
            if failure:
                if not indexed:
                    raise DeepResearchError(failure['code'],'论文原文回读暂不可用')
                if not (missing or benchmarks):
                    return indexed
                return [{**row,**({'pdfMeasurementRead':failure} if i == 0 else {})} for i,row in enumerate(indexed)]
            if not (missing or benchmarks or runtime_tradeoff):
                return include_pdf_representation(indexed, self.pages[key], material, limit)
            passages = self._pdf_passages(pdf_id,material,self.pages[key],record=record)
            # An original PDF has a document hash/version, not an index version.
            passages = [{**row,'versionId':material.get('versionId') or material['contentHash']} for row in passages]
            found = include_pdf_measurements(indexed,passages,query,pdf_id,material['contentHash'],limit)
            from services.deep_research.measurement_table_navigation import retain_threshold_table
            found = retain_threshold_table(found, passages, benchmarks, limit)
            if record.get('comparisonNamedBenchmarkProtocolVersion') in (1, 2):
                from services.deep_research.pdf_benchmark_protocol import include_protocol
                found = include_protocol(found, self.pages[key], material, benchmarks, limit,
                    include_metric_definition=record.get('comparisonNamedBenchmarkProtocolVersion') == 2)
            if representation:
                found = include_pdf_representation(found, self.pages[key], material, limit)
            if runtime_tradeoff:
                from services.deep_research.runtime_evidence import include_pdf_tradeoff
                found = include_pdf_tradeoff(found, passages, limit)
            missing = missing_measurements(found,query)
            note = {'status':'searched','pagesRead':len(self.pages[key]),
                    'unmatchedMeasurements':sorted((str(n),u) for n,u in missing)}
            return [{**row,**({'pdfMeasurementRead':note} if i == 0 else {})} for i,row in enumerate(found)]


    def load_pages(self, pdf_id):
        """Read only the owned snapshot version; recheck scope even on cache hits."""
        if not self.validate(self.run_id, pdf_id):
            raise DeepResearchError("scope_revoked", "论文范围已变更")
        record = self.repo.require_run(self.run_id)
        material = next((value for value in record.get('materials', []) if value.get('materialId') == pdf_id), None)
        if not material or not material.get('contentHash'):
            raise DeepResearchError("source_missing", "论文版本未保存")
        key = (pdf_id, material['contentHash'])
        with self._page_locks_guard:
            lock = self._page_locks.setdefault(key,threading.RLock())
        with lock:
            if not self.validate(self.run_id,pdf_id):
                raise DeepResearchError('scope_revoked','论文范围已变更')
            if key not in self.pages:
                url = f"{self.origin}/task-workspaces/{quote(record['taskId'], safe='')}/materials/{quote(pdf_id, safe='')}/file"
                with self.get(url, timeout=20, stream=True, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise DeepResearchError('source_unavailable','论文文件暂不可读取',{'status_code':response.status_code})
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_LOCAL_PDF_BYTES:
                            raise DeepResearchError('source_too_large', '论文超过正文回查大小上限')
                        chunks.append(chunk)
                body = b''.join(chunks)
                if not body.startswith(b'%PDF-') or hashlib.sha256(body).hexdigest() != material['contentHash']:
                    raise DeepResearchError('source_changed', '论文内容与研究快照不同')
                if self.parse is not None:
                    self.pages[key] = self.parse(body)
                else:
                    self.pages[key] = _parse_pdf(
                        body, include_tables=record.get('comparisonPdfTableFallbackVersion') in (1, 2),
                        **({'include_named_tables':True} if record.get('namedTablePdfFallbackVersion') == 1 else {}),
                        **({'include_declared_arrows':True} if record.get('sourceGlyphContractVersion') == 2 else {}),
                        **({'include_threshold_tables':True} if record.get('comparisonThresholdTablePdfFallbackVersion') == 1 else {}),
                    )
            return material, self.pages[key]


def _read_runtime_tradeoff(record, query):
    from services.deep_research.runtime_evidence import tradeoff_requested
    from services.deep_research.verification import quantity_spelling_for_record

    return quantity_spelling_for_record(record) == 28 and tradeoff_requested(query)


def _requested_metrics(query):
    aliases = {
        'FPS': r'\bfps\b|rendering (?:speed|performance)|渲染速度|帧率',
        'PSNR': r'\bpsnr\b', 'SSIM': r'\bssim\b', 'LPIPS': r'\blpips\b',
        'SIZE': r'\b(?:storage|memory|size|compression)\b|存储|大小|压缩|显存',
    }
    return {metric for metric, pattern in aliases.items() if re.search(pattern, query, re.I)}


def _include_metric_tables(indexed, tables, query, metrics, limit, *, marked_headers=False):
    """Reserve at most two slots for relevant verified rows, keeping prose context.

    This is retrieval only: neither table validity nor ranking establishes that
    a measurement answers the question. Later relevance and claim checks remain.
    """
    ranked = []
    scores = _bm25(query, [row.get('text', '') for row in tables])
    for row, score in zip(tables, scores):
        packet = row.get('tableData')
        if not packet:
            continue
        headers = {m.upper() for _, group in packet['groups'] for m in group}
        if marked_headers:
            headers = {name.rstrip('↑↓').strip() for name in headers}
        if headers & {'MEM', 'MEMORY', 'STORAGE'}:
            headers.add('SIZE')
        overlap = len(headers & metrics)
        if not overlap:
            continue
        own_result = any(re.match(r'^ours(?:\b|_)', method, re.I) for _, method, _ in packet['rows'])
        ranked.append((overlap, own_result, score, row))
    ranked.sort(key=lambda item: item[:3], reverse=True)
    chosen = [item[3] for item in ranked[:min(2, limit - 1)]]
    if not chosen:
        return indexed
    ids = {row['sourceId'] for row in chosen}
    # Keep the best original prose first. Do not spend an extra slot on a table
    # already returned by hybrid retrieval; every source retains its identity.
    rest = [row for row in indexed if row['sourceId'] not in ids]
    return rest[:1] + chosen + rest[1:max(1, limit - len(chosen))]


def _indexed_source(item):
    """Adapt legacy index metadata to the versioned research location contract."""
    metadata = item.get('metadata') or {}
    location = dict(item.get('location') or {})
    page = metadata.get('page')
    page_index = item.get('pageIndex', metadata.get('page_index'))
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        location.setdefault('page', page)
    elif isinstance(page_index, int) and not isinstance(page_index, bool) and page_index >= 0:
        location.setdefault('page', page_index + 1)
    for key, value in [('chunk', item.get('chunkIndex', metadata.get('chunk_index'))),
                       ('section', metadata.get('section_title')), ('table', metadata.get('table_id'))]:
        if value is not None:
            location.setdefault(key, value)
    if metadata.get('table_column_mapping_unverified') is True:
        location['tableColumnMappingUnverified'] = True
    from services.deep_research.table_evidence import visible_table_packet
    packet = visible_table_packet(metadata.get('table_verified_data'), item.get('text', ''))
    return {**item, 'tableData': packet, 'location': location, 'title': item.get('title') or metadata.get('title', ''),
            'retrievalMode': 'indexed_hybrid'}


def _tokens(text):
    return re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]{2}', text.lower())


def _bm25(query, documents):
    tokenized = [_tokens(text) for text in documents]
    average = sum(map(len, tokenized)) / max(len(tokenized), 1) or 1
    terms = set(_tokens(query)) - {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'what', 'how', 'does'}
    frequency = {term: sum(term in tokens for tokens in tokenized) for term in terms}
    scores = []
    for tokens in tokenized:
        score = 0
        for term in terms:
            count = tokens.count(term)
            if count:
                idf = math.log(1 + (len(documents) - frequency[term] + .5) / (frequency[term] + .5))
                score += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * len(tokens) / average))
        scores.append(score)
    return scores


def _parse_pdf(body, *, include_tables=False, include_named_tables=False, include_declared_arrows=False,
               include_threshold_tables=False):
    args = [sys.executable, '-m', 'services.deep_research_pdf_parser', '100', str(MAX_LOCAL_PDF_BYTES)]
    if include_tables:
        args.append('--verified-tables')
    if include_named_tables:
        args.append('--verified-percentage-tables')
    if include_declared_arrows:
        args.append('--declared-font-arrows')
    if include_threshold_tables:
        args.append('--verified-threshold-tables')
    process = subprocess.run(args,
        cwd=str(Path(__file__).resolve().parents[2]), input=body, capture_output=True, timeout=20, check=False)
    if process.returncode or len(process.stdout) > 13_000_000:
        from services.deep_research.pdf_worker_errors import details
        failure=details(process) if process.returncode else {'workerFailureKind':'output_limit'}
        raise DeepResearchError('source_parse_failed', '论文正文回查未完成',failure)
    return json.loads(process.stdout)
