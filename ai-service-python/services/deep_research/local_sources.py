"""Bounded local PDF retrieval when the vector backend is unavailable."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import requests

from services.deep_research.contracts import DeepResearchError


class LocalTaskRetriever:
    def __init__(self, repo, run_id, validate, *, origin, get=requests.get, parse=None):
        self.repo, self.run_id, self.validate = repo, run_id, validate
        self.origin, self.get = origin.rstrip('/'), get
        self.parse = parse or _parse_pdf
        self.pages = {}

    def __call__(self, query, pdf_id, *, limit=5):
        if not self.validate(self.run_id, pdf_id):
            raise DeepResearchError("scope_revoked", "论文范围已变更")
        # Keep the existing indexed route where its runtime is installed.
        if importlib.util.find_spec('sentence_transformers') is not None:
            try:
                from services.research_executor import retrieve_current_paper_evidence
                items = retrieve_current_paper_evidence(query, pdf_id, limit=limit)
                if items:
                    return items
            except (ImportError, RuntimeError, OSError):
                pass
        record = self.repo.require_run(self.run_id)
        material = next((value for value in record.get('materials', []) if value.get('materialId') == pdf_id), None)
        if not material or not material.get('contentHash'):
            raise DeepResearchError("source_missing", "论文版本未保存")
        key = (pdf_id, material['contentHash'])
        if key not in self.pages:
            url = f"{self.origin}/task-workspaces/{quote(record['taskId'], safe='')}/materials/{quote(pdf_id, safe='')}/file"
            with self.get(url, timeout=20, stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise DeepResearchError('source_unavailable', '论文文件暂不可读取')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise DeepResearchError('source_too_large', '论文超过正文回查大小上限')
                    chunks.append(chunk)
            body = b''.join(chunks)
            if not body.startswith(b'%PDF-') or hashlib.sha256(body).hexdigest() != material['contentHash']:
                raise DeepResearchError('source_changed', '论文内容与研究快照不同')
            self.pages[key] = self.parse(body)
        passages = []
        for page in self.pages[key]:
            text = page.get('text', '')
            for offset in range(0, len(text), 1500):
                passage = text[offset:offset + 1800]
                if passage.strip():
                    location = {'page': page['page'], 'offset': offset}
                    identity = hashlib.sha256(f"{pdf_id}:{material['contentHash']}:{location}".encode()).hexdigest()
                    passages.append({'sourceId': 'src_' + identity, 'pdfId': pdf_id, 'text': passage,
                        'location': location, 'contentHash': material['contentHash'], 'versionId': material.get('versionId'),
                        'title': material.get('title', pdf_id), 'accessLevel': 'fulltext', 'retrievalMode': 'pdf_lexical_fallback'})
        scores = _bm25(query, [value['text'] for value in passages])
        ranked = sorted(zip(scores, passages), key=lambda value: -value[0])
        return [value for score, value in ranked[:min(max(int(limit), 0), 5)] if score > 0]


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


def _parse_pdf(body):
    process = subprocess.run([sys.executable, '-m', 'services.deep_research_pdf_parser', '100', str(32 * 1024 * 1024)],
        cwd=str(Path(__file__).resolve().parents[2]), input=body, capture_output=True, timeout=20, check=False)
    if process.returncode or len(process.stdout) > 13_000_000:
        raise DeepResearchError('source_parse_failed', '论文正文回查未完成')
    return json.loads(process.stdout)
