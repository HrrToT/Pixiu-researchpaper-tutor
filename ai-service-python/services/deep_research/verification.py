"""Fail-closed evidence checks, separate from model judgements."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable


def normalize_quote(text: str) -> str:
    # Whitespace is the only permitted transformation of an exact quotation.
    return re.sub(r"\s+", " ", text).strip()


def evidence_id(source: dict, quote: str, location: dict) -> str:
    identity = [source["workId"], source["versionId"], source["contentHash"], location, quote]
    return "ev_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_evidence(source: dict, quote: str, original: str, *, location: dict,
                  obligation_ids: list[str], conditions: dict | None = None) -> dict:
    for key in ("workId", "versionId", "contentHash", "accessLevel"):
        if not isinstance(source.get(key), str) or not source[key]:
            raise ValueError(f"Evidence source missing {key}")
    if source["accessLevel"] not in {"fulltext", "abstract", "user_note"}:
        raise ValueError("Metadata is not textual evidence")
    normalized = normalize_quote(quote)
    if not normalized or normalized not in normalize_quote(original):
        raise ValueError("Quotation does not match original source")
    return {"evidenceId": evidence_id(source, quote, location), "sourceWorkId": source["workId"],
            "sourceVersionId": source["versionId"], "contentHash": source["contentHash"],
            "accessLevel": source["accessLevel"], "quote": quote, "location": dict(location),
            "obligationIds": list(dict.fromkeys(obligation_ids)), "conditions": dict(conditions or {}),
            "verification": {"literal": "passed", "semantic": "unchecked"}}


_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?:\s*%|[x×])?")
_ABSENCE = re.compile(r"未(?:给出|报告|进行|测试|验证)|没有(?:给出|报告|进行|测试)|不存在")
_EXPLICIT_ABSENCE = re.compile(r"\b(?:do|does|did) not\b|\bnot (?:report|evaluat|test|consider)|\bno experiment|未(?:报告|进行|测试|考虑)|没有", re.I)


def verify_claims(claims: list[dict], evidence: list[dict],
                  semantic_check: Callable[[list[dict], list[dict]], list[dict]] | None = None) -> dict:
    """Only publish supported claims; a model cannot override literal checks.

    A semantic checker is a separately budgeted call provided by the graph.
    Missing/malformed/duplicate verdicts fail closed. Suggestions may contain
    proposed numerical settings, but never acquire reported-fact status.
    """
    by_id = {item["evidenceId"]: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("Duplicate evidence identity")
    candidates, rejected, seen = [], [], set()
    for claim in claims:
        claim_id = claim.get("claimId")
        reason = ""
        if not claim_id or claim_id in seen:
            reason = "invalid_identity"
        seen.add(claim_id)
        kind = claim.get("kind")
        refs = claim.get("evidenceRefs", [])
        if kind not in {"reported", "inference", "suggestion", "proposal", "hypothesis"} or not claim.get("text"):
            reason = reason or "invalid_claim"
        if not isinstance(refs, list) or any(ref not in by_id for ref in refs):
            reason = reason or "unknown_evidence"
        support = [by_id[ref] for ref in refs if ref in by_id] if isinstance(refs, list) else []
        if kind in {"reported", "inference"} and not support:
            reason = reason or "missing_evidence"
        if any(item.get("verification", {}).get("literal") != "passed" for item in support):
            reason = reason or "unverified_quotation"
        if kind in {"reported", "inference"} and _ABSENCE.search(claim.get("text", "")):
            scoped = any(word in claim["text"] for word in ("当前取得", "本次检索", "所读片段", "选定片段"))
            if not scoped and not any(_EXPLICIT_ABSENCE.search(item.get("quote", "")) for item in support):
                reason = reason or "absence_not_established"
        if kind == "reported":
            if any(item.get("accessLevel") == "abstract" for item in support) and claim.get("detailLevel") != "abstract":
                reason = reason or "abstract_only"
            claim_text = claim.get("text", "") + " " + json.dumps(claim.get("conditions") or {}, ensure_ascii=False)
            numbers = {normalize_quote(n).replace(" ", "") for n in _NUMBER.findall(claim_text)}
            original_numbers = {normalize_quote(n).replace(" ", "") for item in support for n in _NUMBER.findall(item["quote"])}
            if not numbers <= original_numbers:
                reason = reason or "numeric_mismatch"
        if reason:
            rejected.append({"claimId": claim_id, "reason": reason})
        else:
            candidates.append(dict(claim))
    proposals = {"suggestion", "proposal", "hypothesis"}
    needs_check = [item for item in candidates if item["kind"] not in proposals]
    verdicts: dict[Any, dict] = {}
    if needs_check and semantic_check:
        raw = semantic_check(needs_check, evidence)
        if isinstance(raw, list):
            for verdict in raw:
                if not isinstance(verdict, dict):
                    continue
                key = verdict.get("claimId")
                if key in verdicts:
                    verdicts[key] = {"status": "invalid"}
                else:
                    verdicts[key] = verdict
    accepted = []
    for claim in candidates:
        if claim["kind"] in proposals:
            accepted.append({**claim, "verification": "proposal"})
        elif verdicts.get(claim["claimId"], {}).get("status") == "passed":
            accepted.append({**claim, "verification": "semantic_passed"})
        else:
            rejected.append({"claimId": claim["claimId"], "reason": "semantic_unresolved"})
    return {"accepted": accepted, "rejected": rejected}
