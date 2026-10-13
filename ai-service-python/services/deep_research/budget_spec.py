"""Standalone budget-spec validation and rendering.

This module implements a design protocol only: it checks and renders
budget specifications for prospective experiments. It does not execute
anything and does not produce or claim paper evidence.

Public API:
    BUDGET_SPEC_CONTRACT: str
    validate_budget_spec(spec) -> list[str]   (empty list when valid)
    render_budget_spec(spec) -> str           (empty string when invalid)
    budget_group_errors(budget_spec, group_spec) -> list[str]
"""

from __future__ import annotations

import json
import math

__all__ = [
    "BUDGET_SPEC_CONTRACT",
    "validate_budget_spec",
    "render_budget_spec",
    "budget_group_errors",
]

BUDGET_SPEC_CONTRACT = (
    "Budget role executionSpec (budgetContractVersion=1, server assigned): exactly {baseline,recovery}. "
    "baseline exactly {mode:'train',unit,maxBudget,stoppingRule:nonblank} with finite positive maxBudget, "
    "or exactly {mode:'existing',selectionRule:nonblank} selecting an evidence-backed asset. "
    "Units exactly optimizer_steps|epochs|wall_seconds; steps/epochs require nonbool integers, "
    "seconds permit finite nonbool numbers. recovery exactly {mode:'matched',unit,groups}, "
    "or {mode:'unmatched',unit,groups,note:nonblank budget-confounding explanation}. "
    "groups is a complete binary-ID dict (0=control,1=treatment in factors order) to finite nonnegative "
    "amounts, e.g. two factors need 00,01,10,11. matched requires equal amounts for EVERY group, "
    "including the baseline; all-zero recovery is a diagnostic. Different budgets must be labeled "
    "unmatched and cannot establish matched-budget effects. Do not add a contradictory global default. "
    "These are proposed choices, not paper settings. Existing-asset availability still needs evidence."
)

_TOP_KEYS = frozenset({"baseline", "recovery"})
_ALLOWED_UNITS = frozenset({"optimizer_steps", "epochs", "wall_seconds"})
_BASELINE_TRAIN_KEYS = frozenset({"mode", "unit", "maxBudget", "stoppingRule"})
_BASELINE_EXISTING_KEYS = frozenset({"mode", "selectionRule"})
_RECOVERY_MATCHED_KEYS = frozenset({"mode", "unit", "groups"})
_RECOVERY_UNMATCHED_KEYS = frozenset({"mode", "unit", "groups", "note"})


def _is_nonblank_str(value):
    return isinstance(value, str) and value.strip() != ""


def _is_finite_number(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        try:
            json.dumps(value)
        except (ValueError, OverflowError):
            return False
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _is_finite_positive(value):
    if not _is_finite_number(value):
        return False
    return value > 0


def _check_exact_keys(mapping, expected, label, errors):
    keys = set(mapping.keys())
    for key in sorted(expected - keys):
        errors.append(f"{label}: 缺少键 {key!r}")
    for key in sorted(keys - expected):
        errors.append(f"{label}: 存在多余键 {key!r}")


def _is_binary_string(value):
    return isinstance(value, str) and len(value) > 0 and all(c in "01" for c in value)


def _validate_baseline(baseline, errors):
    if not isinstance(baseline, dict):
        errors.append("baseline: 必须是对象")
        return
    mode = baseline.get("mode")
    if mode == "train":
        _check_exact_keys(baseline, _BASELINE_TRAIN_KEYS, "baseline", errors)
        unit = baseline.get("unit")
        if unit not in _ALLOWED_UNITS:
            errors.append(
                "baseline: unit 必须是 optimizer_steps/epochs/wall_seconds 之一"
            )
        else:
            mb = baseline.get("maxBudget")
            if not _is_finite_positive(mb):
                errors.append(
                    "baseline: maxBudget 必须是有限正数且非布尔"
                )
            elif unit in ("optimizer_steps", "epochs") and not isinstance(mb, int):
                errors.append(
                    "baseline: optimizer_steps/epochs 的 maxBudget 必须是整数"
                )
        if not _is_nonblank_str(baseline.get("stoppingRule")):
            errors.append("baseline: stoppingRule 必须是非空字符串")
    elif mode == "existing":
        _check_exact_keys(baseline, _BASELINE_EXISTING_KEYS, "baseline", errors)
        if not _is_nonblank_str(baseline.get("selectionRule")):
            errors.append("baseline: selectionRule 必须是非空字符串")
    else:
        errors.append("baseline: mode 必须是 'train' 或 'existing'")


def _validate_groups(groups, unit, mode, errors):
    if not isinstance(groups, dict):
        errors.append("recovery.groups: 必须是对象")
        return
    if len(groups) == 0:
        errors.append("recovery.groups: 不能为空")
        return
    if len(groups) < 2:
        errors.append("recovery.groups: 至少需要 2 个分组")
        return

    keys = list(groups.keys())
    for k in keys:
        if not _is_binary_string(k):
            errors.append(f"recovery.groups: 键 {k!r} 不是有效的二进制字符串")
            return

    widths = set(len(k) for k in keys)
    if len(widths) != 1:
        errors.append("recovery.groups: 所有组ID宽度必须相同")
        return
    width = next(iter(widths))
    if width == 0:
        errors.append("recovery.groups: 组ID宽度不能为零")
        return

    count = len(keys)
    if count & (count - 1) or count.bit_length() - 1 != width:
        errors.append(
            f"recovery.groups: 宽度 {width} 的二元分组未完整覆盖，实际有 {count} 个组"
        )
        return

    for gid in sorted(keys):
        val = groups[gid]
        if not _is_finite_number(val):
            errors.append(
                f"recovery.groups[{gid}]: 值必须是有限非负数且非布尔"
            )
            continue
        if val < 0:
            errors.append(f"recovery.groups[{gid}]: 值不能为负")
            continue
        if unit in ("optimizer_steps", "epochs") and not isinstance(val, int):
            errors.append(
                f"recovery.groups[{gid}]: "
                "optimizer_steps/epochs 的值必须是整数"
            )

    if mode == "matched":
        numeric_vals = [
            groups[k]
            for k in keys
            if _is_finite_number(groups[k]) and groups[k] >= 0
        ]
        if len(numeric_vals) >= 2 and len(set(numeric_vals)) != 1:
            errors.append("recovery: matched 模式要求所有组的预算值相等")


def _validate_recovery(recovery, errors):
    if not isinstance(recovery, dict):
        errors.append("recovery: 必须是对象")
        return
    mode = recovery.get("mode")
    if mode == "matched":
        _check_exact_keys(recovery, _RECOVERY_MATCHED_KEYS, "recovery", errors)
    elif mode == "unmatched":
        _check_exact_keys(recovery, _RECOVERY_UNMATCHED_KEYS, "recovery", errors)
        if not _is_nonblank_str(recovery.get("note")):
            errors.append("recovery: unmatched 模式的 note 必须是非空字符串")
    else:
        errors.append("recovery: mode 必须是 'matched' 或 'unmatched'")
        return

    unit = recovery.get("unit")
    if unit not in _ALLOWED_UNITS:
        errors.append(
            "recovery: unit 必须是 optimizer_steps/epochs/wall_seconds 之一"
        )

    groups = recovery.get("groups")
    _validate_groups(groups, unit, mode, errors)


def _validate_spec(spec, errors):
    if not isinstance(spec, dict):
        errors.append("spec 必须是对象")
        return
    _check_exact_keys(spec, _TOP_KEYS, "spec", errors)
    if "baseline" in spec:
        _validate_baseline(spec["baseline"], errors)
    if "recovery" in spec:
        _validate_recovery(spec["recovery"], errors)


def validate_budget_spec(spec):
    """Validate a budget spec; return a stable unique list of error strings.

    Never raises: malformed input fails closed. Does not mutate the input.
    Returns an empty list when the spec is valid.
    """
    errors = []
    try:
        _validate_spec(spec, errors)
    except Exception:
        return ["spec 校验失败（按无效处理）"]
    seen = set()
    unique = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def _escape(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_budget_spec(spec):
    """Render a valid budget spec as a readable Chinese proposed protocol.

    Returns an empty string when the spec is invalid. Never raises and
    never mutates the input. Rendered text describes the proposed design
    only and makes no claims about performed results.
    """
    try:
        if validate_budget_spec(spec):
            return ""
        lines = ["拟议训练与恢复预算（尚未执行）："]
        units = {'optimizer_steps': '优化步', 'epochs': '轮', 'wall_seconds': '秒'}

        baseline = spec["baseline"]
        if baseline["mode"] == "train":
            lines.append(f"- 基线：重新训练，最多{_escape(baseline['maxBudget'])}{units[baseline['unit']]}")
            lines.append(f"- 停止规则：{_escape(baseline['stoppingRule'])}")
        else:
            lines.append(f"- 基线：使用既有资产，选择规则：{_escape(baseline['selectionRule'])}")

        recovery = spec["recovery"]
        label = '各组匹配' if recovery['mode'] == 'matched' else '各组未按相同预算匹配'
        lines.append(f"- 恢复预算：{label}")
        for gid in sorted(recovery["groups"].keys()):
            lines.append(
                f"  - {gid}组：{_escape(recovery['groups'][gid])}{units[recovery['unit']]}"
            )

        if recovery["mode"] == "unmatched":
            lines.append(
                "- 判断边界：结果包含预算混淆因素，不能作为等预算的效应比较"
            )
            lines.append(f"  - 说明：{_escape(recovery['note'])}")

        return "\n".join(lines)
    except Exception:
        return ""


def budget_group_errors(budget_spec, group_spec):
    """Cross-validate budget group IDs against group spec factor arity.

    Lazily imports group_spec. Does not generate all combinations.
    Does not certify scientific comparability or validity.
    """
    budget_errors = validate_budget_spec(budget_spec)
    if budget_errors:
        return budget_errors

    from services.deep_research.group_spec import validate_group_spec

    gs_errors = validate_group_spec(group_spec)
    if gs_errors:
        return gs_errors

    groups = budget_spec["recovery"]["groups"]
    if not groups:
        return []
    width = len(next(iter(groups)))
    n_factors = len(group_spec["factors"])
    if width != n_factors:
        return [
            f"预算组ID宽度 {width} 与因素数量 {n_factors} 不匹配"
        ]
    return []
