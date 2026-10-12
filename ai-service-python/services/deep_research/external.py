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
        flags = capabilities()
        return AcademicSourceClient(AcademicPolicy(enabled=flags["externalAcademic"],
            mode=record["sourcePolicy"]["mode"], allow_fulltext=flags["fulltext"]),
            cache_dir=os.environ.get("DEEP_RESEARCH_SOURCE_DIR", "data/deep_research_sources"))

    def __call__(self, run_id, targets):
        record = self.repo.require_run(run_id)
        if record.get("sourcePolicy", {}).get("mode") not in {"academic_external", "external_only"}:
            return []
        client = self.client_factory(record)
        adapter = ExternalAcademicAdapter(client, self.repo.reserve_call, self.complete_call)
        sources, seen = [], set()
        for target in targets[:4]:
            # Queries contain public topics from the plan, never entire document text.
            query = str(target.get("query", "")).strip()[:700]
            if not query:
                continue
            for candidate in adapter.discover(run_id, query, limit=3):
                identity = candidate.get("versionId")
                if not identity:
                    continue
                if identity in seen:
                    for source in sources:
                        if source.get("versionId") == identity:
                            source["obligationIds"] = list(dict.fromkeys(
                                source.get("obligationIds", []) + [target["obligationId"]]))
                    continue
                seen.add(identity)
                fulltext = (adapter.fetch_fulltext(run_id, candidate["arxivId"]) or {}) if client.policy.allow_fulltext else {}
                material = {**candidate, **fulltext}
                pages = material.get("pages") or [{"text": material.get("abstract", "")}]
                for page in _select_pages(pages, query):
                    text = page.get("text", "")
                    # Keep manageable passages and exact offsets within the original page.
                    for offset in range(0, min(len(text), 6000), 2000):
                        passage = text[offset:offset + 2000]
                        source_id = "src_" + digest({"version": identity, "hash": material["contentHash"],
                                                     "page": page.get("page"), "offset": offset})
                        sources.append({**{key: value for key, value in material.items()
                                           if key not in {"pages", "text", "abstract"}},
                            "sourceId": source_id, "sourceKind": "arxiv", "sourceType": "academic_paper",
                            "ownerMaterialId": material["workId"], "text": passage,
                            "location": {"page": page["page"], "offset": offset} if page.get("page") else {"section": "摘要", "offset": offset},
                            "obligationIds": [target["obligationId"]]})
        return sources


def _select_pages(pages, query):
    words = set(re.findall(r"[a-z]{3,}", query.lower()))
    ranked = sorted(enumerate(pages), key=lambda pair: (
        -sum(pair[1].get("text", "").lower().count(word) for word in words), pair[0]))
    return [page for _, page in ranked[:3] if page.get("text", "").strip()]


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
        if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
            body = path.read_bytes()
            if body.startswith(b"%PDF-") and hashlib.sha256(body).hexdigest() == content_hash:
                result.update(accessLevel="fulltext", pdfBase64=base64.b64encode(body).decode("ascii"))
    return result
