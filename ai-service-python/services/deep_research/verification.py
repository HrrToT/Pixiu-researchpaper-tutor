"""Fail-closed evidence checks, separate from model judgements."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from services.deep_research.asset_availability import requires_existing_asset, enforce_asset_prerequisites


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
            "sourceContext": original,
            "verification": {"literal": "passed", "semantic": "unchecked"}}


def _measurement_numbers(text: str) -> set[str]:
    # Dimensional method labels are not measured quantities. The semantic
    # verifier still checks their identity; standalone dimensions stay checked.
    text = re.sub(r'(?<![A-Za-z0-9_])[234]D(?:-?[A-Za-z]+)?(?![A-Za-z0-9_])', '', text)
    text = re.sub(r'(?<![A-Za-z])Table\s+\d+(?![A-Za-z0-9])|表\s*\d+', '', text, flags=re.I)
    from services.deep_research.measurement_numbers import measurement_numbers
    return measurement_numbers(text)


def _condition_values_text(value):
    # Pure numeric dictionary keys are labels (models may use "1", "2").
    # Other keys can themselves assert a quantity; retain those and every
    # nested value rather than globally erasing metadata digits.
    if isinstance(value, dict):
        return ' '.join(('' if isinstance(key, str) and key.isdigit() else str(key))
                        + ' ' + _condition_values_text(item) for key, item in value.items())
    if isinstance(value, list):
        return ' '.join(_condition_values_text(item) for item in value)
    return str(value) if value is not None else ''


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
        from services.deep_research.prose_checks import absence_not_established, leaks_internal_reference
        if absence_not_established(claim, support):
            reason = reason or 'absence_not_established'
        if leaks_internal_reference(claim, support):
            reason = reason or 'internal_reference_in_prose'
        if kind == "reported":
            if any(item.get("accessLevel") == "abstract" for item in support) and claim.get("detailLevel") != "abstract":
                reason = reason or "abstract_only"
            claim_text = claim.get("text", "") + " " + _condition_values_text(claim.get("conditions") or {})
            # Numbers in parser-established dataset names are identifiers, not
            # measurements (e.g. Mip-NeRF 360). Remove the entire exact label,
            # not its digits globally; wrong numerical claims still fail.
            from services.deep_research.table_bindings import dataset_label
            from services.deep_research.table_evidence import visible_table_packet
            for item in support:
                packet = visible_table_packet(item.get('tableData'), item.get('quote', ''))
                for dataset, _ in packet['groups'] if packet else []:
                    for label in (dataset, dataset_label(dataset)):
                        if any(ch.isalpha() for ch in label):
                            pattern = r'(?<![A-Za-z0-9])' + re.escape(label).replace(r'\ ', r'\s*') + r'(?![A-Za-z0-9])'
                            claim_text = re.sub(pattern, '', claim_text, flags=re.I)
            for item in support:
                # Strip only complete, established identities, longest first.
                # Removing a work-ID prefix from arxiv:...v4 leaves a spurious
                # measurement of 4; an uncited version must remain checked.
                identities = {item.get('sourceWorkId', ''), item.get('sourceVersionId', '')}
                for identity in sorted(identities, key=len, reverse=True):
                    if re.fullmatch(r'arxiv:\d{4}\.\d{4,5}(?:v\d+)?', identity, re.I):
                        pattern = r'(?<![A-Za-z0-9_])' + re.escape(identity) + r'(?![A-Za-z0-9_.])'
                        claim_text = re.sub(pattern, '', claim_text, flags=re.I)
            numbers = _measurement_numbers(claim_text)
            original_numbers = set().union(*(_measurement_numbers(item['quote']) for item in support))
            if not numbers <= original_numbers:
                reason = reason or "numeric_mismatch"
            from services.deep_research.table_bindings import validate_table_bindings
            reason = reason or validate_table_bindings(claim, support)
        if (claim.get('designRole') is not None or
                (claim.get('designContractVersion') == 2 and kind in {'proposal', 'suggestion', 'hypothesis'})):
            from services.deep_research.experimental_reasoning import DESIGN_ROLES
            if not isinstance(claim.get('designRole'), str) or claim['designRole'] not in DESIGN_ROLES or kind not in {'proposal', 'suggestion', 'hypothesis'}:
                reason = reason or 'invalid_design_role'
        if not reason and claim.get('designContractVersion') == 2:
            from services.deep_research.execution_spec import execution_spec_errors
            errors = execution_spec_errors(claim.get('designRole'), claim.get('executionSpec'))
            if errors:
                rejected.append({"claimId": claim_id, "reason": "incomplete_execution_spec",
                                 "detail": ', '.join(errors)})
                continue
        if not reason and 'workflowContractVersion' in claim:
            from services.deep_research.experiment_workflow import workflow_errors, workflow_version
            if (not workflow_version(claim['workflowContractVersion'])
                    or claim.get('designRole') != 'steps' or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_workflow_contract'
            else:
                errors = workflow_errors(claim.get('executionSpec'), claim['workflowContractVersion'])
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_experiment_workflow',
                                     'detail': ', '.join(errors)})
                    continue
        if not reason and 'protocolContractVersion' in claim:
            from services.deep_research.experiment_protocol import protocol_errors, protocol_version, PROTOCOL_ROLES
            if (not protocol_version(claim['protocolContractVersion'])
                    or claim.get('designRole') not in PROTOCOL_ROLES
                    or kind not in {'proposal','suggestion','hypothesis'}):
                reason='invalid_protocol_contract'
            else:
                errors=protocol_errors(claim['designRole'],claim.get('executionSpec'),claim['protocolContractVersion'])
                if errors:
                    rejected.append({'claimId':claim_id,'reason':'incomplete_experiment_protocol','detail':', '.join(errors)})
                    continue
        if not reason and 'budgetContractVersion' in claim:
            from services.deep_research.budget_spec import validate_budget_spec
            if (type(claim['budgetContractVersion']) is not int or claim['budgetContractVersion'] != 1
                    or claim.get('designRole') != 'budget'
                    or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_budget_contract'
            else:
                errors = validate_budget_spec(claim.get('executionSpec'))
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_budget_spec',
                                     'detail': ', '.join(errors)})
                    continue
        if not reason and 'hypothesisContractVersion' in claim:
            from services.deep_research.hypothesis_spec import validate_hypothesis_spec
            if (type(claim['hypothesisContractVersion']) is not int or claim['hypothesisContractVersion'] != 1
                    or claim.get('designRole') != 'hypothesis'
                    or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_hypothesis_contract'
            else:
                errors = validate_hypothesis_spec(claim.get('executionSpec'))
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_hypothesis_spec',
                                     'detail': ', '.join(errors)})
                    continue
        if reason:
            rejected.append({"claimId": claim_id, "reason": reason})
        else:
            candidates.append(dict(claim))
    proposals = {"suggestion", "proposal", "hypothesis"}
    # Suggestions are not established facts, but still need a logic/identity check.
    # A model must not hide a measured result or an invalid formula behind this tag.
    needs_check = candidates
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
        if verdicts.get(claim["claimId"], {}).get("status") == "passed":
            accepted.append({**claim, "verification": "proposal" if claim["kind"] in proposals else "semantic_passed",
                             **({'assetAvailability': verdicts[claim['claimId']].get('assetAvailability')}
                                if requires_existing_asset(claim) else {})})
        else:
            verdict = verdicts.get(claim["claimId"], {})
            rejected.append({"claimId": claim["claimId"], "reason": "semantic_unresolved",
                             "detail": str(verdict.get("reason", ""))[:400]})
    asset_ids = {c.get('claimId') for c in claims if requires_existing_asset(c)}
    for row in rejected:
        if row.get('claimId') in asset_ids:
            row['assetPrerequisite'] = True
    return enforce_asset_prerequisites({"accepted": accepted, "rejected": rejected}, evidence)
