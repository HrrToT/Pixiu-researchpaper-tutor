"""Evidence-only gate: reject missing or unsupported design-audit quotes."""

import json

REQUIRED = {
    "groups": ("group_construction", "intervention_levels"),
    "data": ("scenes", "split", "seeds", "sampling_unit"),
    "metrics": ("quality_protocol", "speed_protocol", "storage_protocol"),
    "budget": ("per_group_steps",),
    "analysis": ("effects", "uncertainty", "decision_rule"),
}

_ALLOWED_REFERENCE_KINDS = ("proposal", "suggestion", "hypothesis")


def required_design_slots(metric_domains=None):
    from services.deep_research.metric_scope import metric_protocol_requirements
    return {**REQUIRED, 'metrics': tuple(f'{domain}_protocol'
            for domain in metric_protocol_requirements(metric_domains))}


def validate_design_audit(claim, verdict, context, metric_domains=None):
    role = claim.get("designRole") if isinstance(claim, dict) else None
    if not isinstance(role, str):
        return []
    slots = required_design_slots(metric_domains).get(role)
    if slots is None:
        return []

    audit = verdict.get("designAudit") if isinstance(verdict, dict) else None
    # Accept the observed unambiguous role wrapper without weakening slot checks.
    if isinstance(audit, dict) and set(audit) == {role} and isinstance(audit[role], dict):
        audit = audit[role]
    if not isinstance(audit, dict):
        return list(slots)

    failed = []
    for slot in slots:
        if not _slot_supported(audit.get(slot), claim, context):
            failed.append(slot)
    return failed


def _slot_supported(entry, claim, context):
    if not isinstance(entry, dict):
        return False
    claim_id = entry.get("claimId")
    quote = entry.get("quote")
    if not isinstance(claim_id, str) or not isinstance(quote, str) or not quote.strip():
        return False
    reference = _resolve_reference(claim, context, claim_id)
    if reference is None:
        return False
    return any(quote in text for text in _reference_texts(reference))


def _resolve_reference(claim, context, claim_id):
    if (isinstance(claim, dict) and claim.get("claimId") == claim_id
            and claim.get("kind") in _ALLOWED_REFERENCE_KINDS):
        return claim
    if isinstance(context, list):
        for entry in context:
            if not isinstance(entry, dict):
                continue
            if entry.get("claimId") != claim_id:
                continue
            if entry.get("kind") in _ALLOWED_REFERENCE_KINDS:
                return entry
            return None
    return None


def _reference_texts(entry):
    texts = []
    text = entry.get("text")
    if isinstance(text, str):
        texts.append(text)
    conditions = entry.get("conditions")
    if conditions is not None:
        try:
            texts.append(json.dumps(conditions, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
    return texts
