"""Hypothesis spec validation, linkage checking and rendering (stdlib only)."""

import json

HYPOTHESIS_SPEC_CONTRACT = (
    "Hypothesis role executionSpec (hypothesisContractVersion=1, server assigned) defines a "
    "proposed, unexecuted hypothesis and its decision scope. "
    "Exact keys: statement (nonblank prospective hypothesis text), "
    "analysisClaimId (nonblank str matching an accepted analysis claim), "
    "effectKeys (nonempty unique list of nonblank str, each must be an exact key "
    "in the linked analysis executionSpec effects dict), "
    "purpose (exactly explore|test_zero|assess_equivalence). "
    "Purpose must match the linked analysis decision.mode: explore->descriptive, "
    "test_zero->interval_excludes_zero, assess_equivalence->equivalence. "
    "Select the purpose required by the user, not a weaker substitute. "
    "Extra or missing keys reject. Typed linkage alone "
    "does not validate scientific correctness of the statement or assumptions."
)

_REQUIRED_KEYS = frozenset({"statement", "analysisClaimId", "effectKeys", "purpose"})
PURPOSE_DECISIONS = {
    "explore": "descriptive",
    "test_zero": "interval_excludes_zero",
    "assess_equivalence": "equivalence",
}
_PURPOSES = frozenset(PURPOSE_DECISIONS)

_EFFECT_LABELS = {
    'A_cond_B0': 'B=0时A的条件效应', 'A_cond_B1': 'B=1时A的条件效应',
    'B_cond_A0': 'A=0时B的条件效应', 'B_cond_A1': 'A=1时B的条件效应',
    'A_main': 'A的平均主效应', 'B_main': 'B的平均主效应', 'interaction': '交互效应',
}

_PURPOSE_TEXT = {
    'explore': '本假设用于探索：报告估计值和可提供的不确定性说明，但不做显著性或等价性判定。',
    'test_zero': '本假设用于零效应检验：按置信区间是否排除零作判断；区间排除零时按预定置信水平拒绝零效应假设，非显著结果不等于效应不存在。',
    'assess_equivalence': '本假设用于等价性评估：完整不确定区间须落入已声明的容差范围，才能判断实际等价；不预先宣布结果。',
}


def _is_nonblank_str(v):
    return isinstance(v, str) and v.strip() != ""


def _all_unique(seq):
    try:
        return len(set(seq)) == len(seq)
    except TypeError:
        return False


def validate_hypothesis_spec(spec):
    """Return stable unique field-path errors. Never raises; never mutates."""
    errors = []
    seen = set()

    def add(path):
        if path not in seen:
            seen.add(path)
            errors.append(path)

    if not isinstance(spec, dict):
        add("spec")
        return errors

    keys = set(spec.keys())
    for missing in sorted(_REQUIRED_KEYS - keys):
        add(missing)
    for extra in sorted(keys - _REQUIRED_KEYS, key=str):
        add(str(extra))

    if "statement" in keys:
        if not _is_nonblank_str(spec["statement"]):
            add("statement")

    if "analysisClaimId" in keys:
        if not _is_nonblank_str(spec["analysisClaimId"]):
            add("analysisClaimId")

    if "effectKeys" in keys:
        ek = spec["effectKeys"]
        if not isinstance(ek, list) or len(ek) == 0:
            add("effectKeys")
        else:
            for i, item in enumerate(ek):
                if not _is_nonblank_str(item):
                    add(f"effectKeys[{i}]")
            if not _all_unique(ek):
                add("effectKeys")

    if "purpose" in keys:
        p = spec["purpose"]
        try:
            if p not in _PURPOSES:
                add("purpose")
        except TypeError:
            add("purpose")

    return errors


def render_hypothesis_spec(spec):
    """Render Chinese readable hypothesis text. Empty string if invalid."""
    if validate_hypothesis_spec(spec):
        return ""

    statement = spec["statement"]
    effect_keys = spec["effectKeys"]
    purpose = spec["purpose"]

    parts = []
    parts.append("\u62df\u8bae\u5047\u8bbe\u4e0e\u5224\u65ad\u8303\u56f4\uff08\u5c1a\u672a\u9a8c\u8bc1\uff09")
    parts.append("")
    parts.append("\u5047\u8bbe\u9648\u8ff0\uff1a" + json.dumps(statement, ensure_ascii=False))
    parts.append("")
    parts.append("\u5173\u6ce8\u6548\u5e94\uff1a")
    for ek in effect_keys:
        label = _EFFECT_LABELS.get(ek, ek)
        parts.append("  - " + json.dumps(label, ensure_ascii=False))
    parts.append("")
    parts.append(_PURPOSE_TEXT[purpose])

    return "\n".join(parts)


def hypothesis_analysis_errors(spec, analysis_claim):
    """Validate typed linkage between hypothesis spec and analysis claim.

    Returns stable unique error strings. Never mutates inputs; no network.
    """
    errors = []
    seen = set()

    def add(path):
        if path not in seen:
            seen.add(path)
            errors.append(path)

    spec_errors = validate_hypothesis_spec(spec)
    for e in spec_errors:
        add(f"spec.{e}")

    if spec_errors:
        return errors

    if not isinstance(analysis_claim, dict):
        add("analysis_claim")
        return errors

    claim_id = analysis_claim.get("claimId")
    if claim_id != spec["analysisClaimId"]:
        add("analysis_claim.claimId")

    kind = analysis_claim.get("kind")
    if kind not in ("proposal", "suggestion", "hypothesis"):
        add("analysis_claim.kind")

    design_role = analysis_claim.get("designRole")
    if design_role != "analysis":
        add("analysis_claim.designRole")

    execution_spec = analysis_claim.get("executionSpec")
    from services.deep_research.execution_spec import execution_spec_errors
    exec_errors = execution_spec_errors("analysis", execution_spec)
    for e in exec_errors:
        add(f"analysis_claim.executionSpec.{e}")

    if isinstance(execution_spec, dict):
        effects_dict = execution_spec.get("effects")
        if isinstance(effects_dict, dict):
            for ek in spec["effectKeys"]:
                if ek not in effects_dict:
                    add(f"effectKeys.{ek}")

    purpose = spec["purpose"]
    expected_mode = PURPOSE_DECISIONS[purpose]
    if isinstance(execution_spec, dict):
        decision = execution_spec.get("decision")
        if isinstance(decision, dict):
            actual_mode = decision.get("mode")
            if actual_mode != expected_mode:
                add("purpose_decision_mismatch")

    return errors
