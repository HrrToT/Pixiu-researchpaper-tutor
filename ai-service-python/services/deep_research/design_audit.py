"""Evidence-only gate: reject missing or unsupported design-audit quotes."""

import json
from services.deep_research.experiment_workflow import workflow_version

REQUIRED = {
    "groups": ("group_construction", "intervention_levels"),
    "controls": ("paired_initialization", "render_settings", "optimizer_settings", "other_interventions"),
    "data": ("scenes", "split", "seeds", "sampling_unit"),
    "metrics": ("quality_protocol", "speed_protocol", "storage_protocol"),
    "budget": ("per_group_steps",),
    "steps": ("baseline_acquisition", "group_pairing", "saved_artifacts"),
    "analysis": ("effects", "uncertainty", "decision_rule"),
}

_ALLOWED_REFERENCE_KINDS = ("proposal", "suggestion", "hypothesis")


def required_design_slots(metric_domains=None):
    from services.deep_research.metric_scope import metric_protocol_requirements
    return {**REQUIRED, 'metrics': tuple(f'{domain}_protocol'
            for domain in metric_protocol_requirements(metric_domains))}


def design_slots_for_claim(claim, metric_domains=None):
    role = claim.get('designRole')
    slots = required_design_slots(metric_domains).get(role)
    if role == 'steps' and workflow_version(claim.get('workflowContractVersion')):
        slots = (*slots, 'data_isolation', 'component_creation', 'seed_pairing', 'checkpoint_selection')
        if claim['workflowContractVersion'] == 5:
            slots = (*slots, 'timeline_dependencies', 'state_lifetime', 'stage_group_accounting', 'evaluation_readonly')
    return slots


def validate_design_audit(claim, verdict, context, metric_domains=None, *, direct_fields=False):
    role = claim.get("designRole") if isinstance(claim, dict) else None
    if not isinstance(role, str):
        return []
    slots = design_slots_for_claim(claim, metric_domains)
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
        entry = audit.get(slot)
        # Contract 2 accepts only the exact, unambiguous single-field shape.
        # Reuse ALL existing value/path/role/version and recovery-slot checks.
        if direct_fields is True and isinstance(entry, dict) and set(entry) == {'claimId', 'path', 'value'}:
            entry = {'fields': [entry]}
        if not _slot_supported(entry, claim, context, slot):
            failed.append(slot)
    return failed


def _slot_supported(entry, claim, context, slot=None):
    if not isinstance(entry, dict):
        return False
    if slot in _TIMELINE_WHOLE_ROOTS and not ({'fields','ref'} & entry.keys()):
        return False
    if 'ref' in entry:
        reference = entry['ref']
        if set(entry) != {'ref'} or not isinstance(reference, dict) or set(reference) != {'claimId', 'path'}:
            return False
        path = reference['path']
        if not isinstance(path, list):
            return False
        source = _resolve_reference(claim, context, reference['claimId'])
        value = source
        for key in path:
            if isinstance(value, dict) and isinstance(key, str) and key in value:
                value = value[key]
            elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
                value = value[key]
            else:
                return False
        # A single reference is the same binding as a one-entry fields list.
        # Reuse its slot-level requirements as well as path/value validation;
        # baseline preparation alone cannot establish per-group recovery.
        return _slot_supported({'fields': [{**reference, 'value': value}]}, claim, context, slot)
    if 'fields' in entry:
        fields = entry['fields']
        if set(entry) != {'fields'} or not isinstance(fields, list) or not 1 <= len(fields) <= 32:
            return False
        if slot == 'per_group_steps' and not any(isinstance(field, dict)
                and isinstance(field.get('path'), list)
                and field['path'][:2] == ['executionSpec', 'recovery'] for field in fields):
            return False
        if slot in _TIMELINE_WHOLE_ROOTS:
            for root in _TIMELINE_WHOLE_ROOTS[slot]:
                if not any(isinstance(field, dict) and field.get('claimId') == claim.get('claimId')
                           and field.get('path') == ['executionSpec', root] for field in fields):
                    return False
        return all(_field_supported(field, claim, context, slot) for field in fields)
    if 'quotes' in entry:
        # Non-contiguous choices retain their own source identities. Never
        # split or normalize a fabricated combined quotation on the caller's behalf.
        segments = entry['quotes']
        if set(entry) != {'quotes'} or not isinstance(segments, list) or not 1 <= len(segments) <= 32:
            return False
        return all(isinstance(segment, dict) and not {'quotes', 'fields'} & set(segment)
                   and _slot_supported(segment, claim, context, slot) for segment in segments)
    claim_id = entry.get("claimId")
    quote = entry.get("quote")
    if not isinstance(claim_id, str) or not isinstance(quote, str) or not quote.strip():
        return False
    reference = _resolve_reference(claim, context, claim_id)
    if reference is None:
        return False
    return any(quote in text for text in _reference_texts(reference))


_FIELD_ROOTS = {
    'intervention_levels': ('groups', {'factors'}),
    'scenes': ('data', {'dataset', 'scenes'}),
    'split': ('data', {'split'}),
    'seeds': ('data', {'seeds'}),
    'sampling_unit': ('data', {'independentUnit'}),
    'effects': ('analysis', {'effects'}),
    'uncertainty': ('analysis', {'uncertainty'}),
    'decision_rule': ('analysis', {'decision'}),
    'per_group_steps': ('budget', {'baseline', 'recovery'}),
    'paired_initialization': ('controls', {'initialization'}),
    'render_settings': ('controls', {'rendering'}),
    'optimizer_settings': ('controls', {'optimizer'}),
    'other_interventions': ('controls', {'otherInterventions'}),
    'baseline_acquisition': ('steps', {'refs', 'baselineMode', 'baselineInitialization', 'order'}),
    'group_pairing': ('steps', {'refs', 'componentInitializations', 'replicationMode', 'order'}),
    'saved_artifacts': ('steps', {'records'}),
    'data_isolation': ('steps', {'order', 'checkpointSelection'}),
    'component_creation': ('steps', {'baselineInitialization', 'componentInitializations'}),
    'seed_pairing': ('steps', {'replicationMode', 'refs'}),
    'checkpoint_selection': ('steps', {'checkpointSelection'}),
    'timeline_dependencies': ('steps', {'phases','componentInitializations'}),
    'state_lifetime': ('steps', {'componentInitializations'}),
    'stage_group_accounting': ('steps', {'phases','frameIterations'}),
    'evaluation_readonly': ('steps', {'phases'}),
}

_TIMELINE_WHOLE_ROOTS = {
    'timeline_dependencies': ('phases','componentInitializations'),
    'state_lifetime': ('componentInitializations',),
    'stage_group_accounting': ('phases','frameIterations'),
    'evaluation_readonly': ('phases',),
}


def audit_field_roots(slots, *, workflow_v4=False):
    """Describe only active slots, using the validator's exact role/root rules."""
    return {slot: {'role': _FIELD_ROOTS[slot][0], 'roots': sorted(_FIELD_ROOTS[slot][1]
            - (set() if workflow_v4 else {'baselineInitialization'}))}
            for slot in slots if slot in _FIELD_ROOTS}


def _field_supported(field, claim, context, slot):
    """Bind an exact typed value, not a generated paraphrase or a truth verdict."""
    if not isinstance(field, dict) or set(field) != {'claimId', 'path', 'value'}:
        return False
    path = field['path']
    if (not isinstance(field['claimId'], str) or not isinstance(path, list)
            or not 2 <= len(path) <= 12 or path[0] != 'executionSpec'):
        return False
    reference = _resolve_reference(claim, context, field['claimId'])
    allowed = _FIELD_ROOTS.get(slot)
    if (reference is None or allowed is None or reference.get('designRole') != allowed[0]
            or not isinstance(path[1], str) or path[1] not in allowed[1]):
        return False
    from services.deep_research.execution_spec import execution_spec_errors
    if reference.get('designRole') == 'budget':
        from services.deep_research.budget_spec import validate_budget_spec
        if (type(reference.get('budgetContractVersion')) is not int
                or reference['budgetContractVersion'] != 1
                or validate_budget_spec(reference.get('executionSpec'))):
            return False
    if execution_spec_errors(reference.get('designRole'), reference.get('executionSpec')):
        return False
    if reference.get('designRole') == 'steps' or 'workflowContractVersion' in reference:
        from services.deep_research.experiment_workflow import workflow_errors
        if (not workflow_version(reference.get('workflowContractVersion'))
                or reference.get('designRole') != 'steps'
                or workflow_errors(reference.get('executionSpec'), reference['workflowContractVersion'])):
            return False
    if reference.get('designRole')=='controls' or 'protocolContractVersion' in reference:
        from services.deep_research.experiment_protocol import protocol_errors, protocol_version
        version = protocol_version(reference.get('protocolContractVersion'))
        if (not version or protocol_errors(reference.get('designRole'),reference.get('executionSpec'),version)):
            return False
    value = reference
    for key in path:
        if isinstance(value, dict) and isinstance(key, str) and key in value:
            value = value[key]
        elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
            value = value[key]
        else:
            return False
    declared_no_components = (reference.get('workflowContractVersion') == 5
        and slot in {'component_creation','group_pairing',*_TIMELINE_WHOLE_ROOTS}
        and path == ['executionSpec','componentInitializations'] and type(value) is list and value == [])
    if not declared_no_components and (value is None or value == '' or value == [] or value == {}):
        return False
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(
            field['value'], sort_keys=True, allow_nan=False)
    except (ValueError, TypeError):
        return False


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
