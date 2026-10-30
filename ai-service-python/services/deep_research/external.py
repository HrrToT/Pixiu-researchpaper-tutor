"""Acquire bounded academic sources through the same durable call ledger."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.tools import ExternalAcademicAdapter
from services.deep_research_academic import AcademicPolicy, AcademicSourceClient


def capabilities():
    enabled = os.environ.get("DEEP_RESEARCH_V2_ENABLED", "false").lower() == "true"
    external = enabled and os.environ.get("DEEP_RESEARCH_EXTERNAL_ENABLED", "false").lower() == "true"
    return {"engineVersion": "deep-research-v2", "enabled": enabled,
            "externalAcademic": external,
            "fulltext": external and os.environ.get("DEEP_RESEARCH_FULLTEXT_ENABLED", "false").lower() == "true",
            "budgetProfiles": ["standard", "extended"]}


class AcademicAcquisition:
    def __init__(self, repo, complete_call, *, client_factory=None):
        self.repo = repo
        self.complete_call = complete_call
        self.client_factory = client_factory or self._client

    def _client(self, record):
        from core.config import settings
        flags = capabilities()
        return AcademicSourceClient(AcademicPolicy(enabled=flags["externalAcademic"],
            mode=record["sourcePolicy"]["mode"], allow_fulltext=flags["fulltext"],
            max_pdf_bytes=settings.deep_research_max_pdf_bytes),
            proxy_url=settings.deep_research_http_proxy,
            cache_dir=os.environ.get("DEEP_RESEARCH_SOURCE_DIR", "data/deep_research_sources"))

    def __call__(self, run_id, targets):
        record = self.repo.require_run(run_id)
        if record.get("sourcePolicy", {}).get("mode") not in {"academic_external", "external_only"}:
            return []
        client = self.client_factory(record)
        adapter = ExternalAcademicAdapter(client, self.repo.reserve_call, self.complete_call)
        sources, materials, by_source = [], {}, {}
        for target in targets[:4]:
            # Queries contain public topics from the plan, never entire document text.
            query = str(target.get("query", "")).strip()[:700]
            identities = []
            if record.get('exactDiscoveryContractVersion') == 1:
                from services.deep_research_academic import checked_arxiv_id
                for identity in target.get('requiredSources', []):
                    if isinstance(identity, str) and identity.startswith('arxiv:'):
                        identities.append(checked_arxiv_id(identity[6:]))
                missing = target.get('missingSource')
                if isinstance(missing, str) and missing.startswith('arxiv:'):
                    identities = [checked_arxiv_id(missing[6:])]
                identities = list(dict.fromkeys(identities))
            if not query and not identities:
                continue
            # Source identity and reading question serve different purposes.
            # Editing the question cannot turn a pinned paper into topic search.
            candidates = (adapter.lookup(run_id, identities, limit=max(3, len(identities)))
                          if identities else adapter.discover(run_id, query, limit=3))
            for candidate in candidates:
                identity = candidate.get("versionId")
                if not identity:
                    continue
                if identity not in materials:
                    fulltext = (adapter.fetch_fulltext(run_id, candidate["arxivId"]) or {}) if client.policy.allow_fulltext else {}
                    # Cache acquisition, not the passages selected for one question.
                    materials[identity] = {**candidate, **fulltext, "url": candidate.get("url", ""),
                                           "discoveredAt": candidate.get('retrievedAt')}
                material = materials[identity]
                pages = material.get("pages") or [{"text": material.get("abstract", "")}]
                question = str(target.get('question') or '')
                # A Chinese question can contain only the English paper name.
                # Always retain the translated discovery terms as well: a title
                # match alone does not locate the requested method passage.
                reading_query = question + ' ' + query
                for page in _select_pages(pages, reading_query, title=material.get('title', '')):
                    text = page.get("text", "")
                    # Keep manageable passages and exact offsets within the original page.
                    for offset, passage in _page_passages(text):
                        source_id = "src_" + digest({"version": identity, "hash": material["contentHash"],
                                                     "page": page.get("page"), "offset": offset,
                                                     "endOffset": offset + len(passage)})
                        if source_id in by_source:
                            existing = by_source[source_id]
                            existing['obligationIds'] = list(dict.fromkeys(
                                existing['obligationIds'] + [target['obligationId']]))
                            continue
                        source = {**{key: value for key, value in material.items()
                                           if key not in {"pages", "text", "abstract"}},
                            "sourceId": source_id, "sourceKind": "arxiv", "sourceType": "academic_paper",
                            "ownerMaterialId": material["workId"], "text": passage,
                            "location": {"page": page["page"], "offset": offset} if page.get("page") else {"section": "摘要", "offset": offset},
                            "obligationIds": [target["obligationId"]]}
                        sources.append(source)
                        by_source[source_id] = source
        if not sources and adapter.discovery_outcomes and all(
                outcome == 'failed' for outcome in adapter.discovery_outcomes):
            raise DeepResearchError('external_discovery_unavailable', '外部文献获取失败')
        return sources


def _page_passages(text):
    """Use exact page slices, preferring complete sentences over fixed cuts.

    Keep the existing 6000-character page envelope and the extractor's
    3000-character passage cap. No normalization or invented punctuation.
    """
    limit, offset = min(len(text), 6000), 0
    boundaries = [match.end() for match in re.finditer(r'(?<=[.!?。！？])\s+|\n[ \t]*\n', text[:limit])]
    while offset < limit:
        end = min(offset + 2000, limit)
        if end < limit:
            following = next((point for point in boundaries if end <= point <= min(offset + 3000, limit)), None)
            if following is not None:
                end = following
            else:
                # A long sentence still keeps whole words where possible.
                spaces = list(re.finditer(r'\s+', text[max(offset, end - 200):end]))
                if spaces:
                    end = max(offset, end - 200) + spaces[-1].end()
        yield offset, text[offset:end]
        offset = end


def _reading_terms(query):
    # Discovery identifiers locate a paper, not a passage inside it. Counting
    # 'arxiv' rewards bibliography pages and masks translated mechanism terms.
    topic = re.sub(r'https?://\S+|\b10\.\d{4,9}/\S+', ' ', query.lower())
    stop = {'arxiv', 'doi', 'preprint', 'www', 'http', 'https', 'org',
            'the', 'and', 'for', 'with', 'from', 'this', 'that', 'what',
            'which', 'how', 'does', 'are', 'its', 'all'}
    return set(re.findall(r'[a-z]{3,}', topic)) - stop


def _select_pages(pages, query, *, title=''):
    words = _reading_terms(query)
    # A one-word paper identifier before ':' locates the work, not its method.
    # It often repeats in page headers and can otherwise displace the passage
    # explaining the requested operation. Keep substantive multiword titles.
    label, separator, _ = str(title).partition(':')
    if separator and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', label.strip()):
        topic_words = words - _reading_terms(label)
        if topic_words:
            words = topic_words
    def rank(pair):
        text = pair[1].get('text', '').lower()
        counts = [text.count(word) for word in words]
        # Distinct requested concepts outrank repetition of a single keyword.
        return (-sum(count > 0 for count in counts), -sum(min(count, 3) for count in counts), pair[0])
    ranked = sorted(((i, page) for i, page in enumerate(pages) if page.get('text', '').strip()), key=rank)
    return [page for _, page in ranked[:3]]


def export_saved_source(repo, run_id, source_id):
    """Export only already acquired content; this action never fetches a URL."""
    record = repo.require_run(run_id)
    source = next((s for s in record.get("state", {}).get("sources", [])
                   if s.get("sourceId") == source_id and s.get("sourceKind") == "arxiv"), None)
    if source is None or record.get("sourcePolicy", {}).get("mode") not in {"academic_external", "external_only"}:
        raise DeepResearchError("source_missing", "该来源未在此研究中取得")
    result = {key: source.get(key) for key in ("sourceId", "workId", "versionId", "arxivId", "title", "url", "contentHash")}
    result["accessLevel"] = "metadata"
    if source.get("accessLevel") == "abstract":
        result["abstract"] = source.get("text", "")[:10000]
    content_hash = source.get("contentHash", "")
    if source.get("accessLevel") == "fulltext" and re.fullmatch(r"[a-f0-9]{64}", content_hash):
        path = Path(os.environ.get("DEEP_RESEARCH_SOURCE_DIR", "data/deep_research_sources")) / (content_hash + ".pdf")
        from core.config import settings
        if path.is_file() and path.stat().st_size <= settings.deep_research_max_pdf_bytes:
            body = path.read_bytes()
            if body.startswith(b"%PDF-") and hashlib.sha256(body).hexdigest() == content_hash:
                result.update(accessLevel="fulltext", pdfBase64=base64.b64encode(body).decode("ascii"))
    return result
