"""Advisory pool-selection helper for deep-research finalization nodes.

``select_reservation_pool`` is a PURE, read-only helper invoked inside an
open database transaction *before* the authoritative budget-validation path.
It never mutates budgets, never increases limits, never consumes capacity,
and never bypasses status/time/unknown-call guards. Eligible finalization nodes
can fall back to available normal capacity after the protected call slots run
out. Versioned server-created budgets may also release unused protected tokens
for those calls. The repository records that release in the same transaction
as the reservation; total token and call limits remain unchanged.

Return value semantics:
  * ``True``  – caller should attempt the protected reserve pool.
  * ``False`` – caller should attempt the normal pool.

The returned bool does **not** prove call admission; the repository still
performs full authoritative checks and records the actual pool used.
"""

from __future__ import annotations

from typing import Any

__all__ = ["select_reservation_pool", "prepare_finalization_budget", "released_reserve_tokens"]

_FINALIZATION_NODES: frozenset[str] = frozenset(
    {
        "synthesize",
        "plan_experiment",
        "verify",
        "verify_repair",
        "verify_design_config",
        "verify_repair_design_config",
        "verify_design_science",
        "verify_repair_design_science",
        "verify_answer_coverage",
    }
)

_LIMIT_FIELDS = ("maxModelCalls", "reserveModelCalls", "maxTokens", "reserveTokens")
_USED_FIELDS = ("modelCalls", "reservedModelCalls", "normalTokens", "tokens")


def _valid_nonneg_int(value: Any) -> bool:
    """Return True when *value* is an int >= 0 and NOT a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def released_reserve_tokens(budget):
    """Read only the versioned server-owned transfer, never a wider total cap."""
    if type(budget.get('finalizationBudgetVersion')) is not int or budget['finalizationBudgetVersion'] != 1:
        return 0
    value, reserve = budget.get('releasedReserveTokens', 0), budget.get('reserveTokens', 0)
    if not _valid_nonneg_int(value) or not _valid_nonneg_int(reserve) or value > reserve:
        return 0
    return value


def eligible_finalization_request(budget, requested_reserve, node):
    return (isinstance(budget, dict) and type(budget.get('finalizationBudgetVersion')) is int
            and budget['finalizationBudgetVersion'] == 1 and requested_reserve is True
            and isinstance(node, str) and node in _FINALIZATION_NODES)


def prepare_finalization_budget(budget, delta, requested_reserve, node):
    """Release unused protected tokens only after protected call slots run out.

    Pure advisory copy. The repository applies it atomically with the actual
    reservation, after running/time/unknown guards. No limit or usage changes.
    Legacy budgets keep their original partition and are never opted in here.
    """
    if not eligible_finalization_request(budget, requested_reserve, node) or not isinstance(delta, dict):
        return budget
    fields = (*_LIMIT_FIELDS, *_USED_FIELDS, 'releasedReserveTokens')
    if any(not _valid_nonneg_int(budget.get(key, 0)) for key in fields):
        return budget
    count = delta.get('modelCalls', 0)
    cost = delta.get('tokens', 0)
    if not _valid_nonneg_int(count) or count <= 0 or not _valid_nonneg_int(cost):
        return budget
    maximum, reserve = budget.get('maxTokens', 0), budget.get('reserveTokens', 0)
    calls, protected = budget.get('maxModelCalls', 0), budget.get('reserveModelCalls', 0)
    normal, used = budget.get('normalTokens', 0), budget.get('tokens', 0)
    ordinary, final = budget.get('modelCalls', 0), budget.get('reservedModelCalls', 0)
    released = budget.get('releasedReserveTokens', 0)
    if (maximum <= 0 or calls <= 0 or reserve > maximum or protected > calls or released > reserve
            or normal > used or used + cost > maximum or final != protected
            or ordinary + count > calls - protected
            or ordinary + final + count > calls):
        return budget
    unused = max(0, reserve - (used - normal))
    return {**budget, 'releasedReserveTokens': max(released, unused)}


def select_reservation_pool(
    budget: Any,
    delta: Any,
    requested_reserve: bool,
    node: Any,
) -> bool:
    """Advisory pool selector – never mutates *budget* or *delta*.

    Returns *requested_reserve* unchanged in every case **except** when all
    fallback conditions are satisfied for an authorised finalization node,
    in which case it returns ``False`` (use normal pool).
    """

    budget = prepare_finalization_budget(budget, delta, requested_reserve, node)
    # --- fast-path: nothing to do unless caller asked for the reserve pool.
    if requested_reserve is not True:
        return requested_reserve

    # --- node must be an authorised finalization node.
    try:
        if node not in _FINALIZATION_NODES:
            return requested_reserve
    except TypeError:
        # Unhashable node (e.g. list/dict) – cannot match.
        return requested_reserve

    # --- both arguments must be plain dicts.
    if not isinstance(budget, dict) or not isinstance(delta, dict):
        return requested_reserve

    # --- delta.modelCalls must be a positive int (bool excluded).
    delta_model_calls: Any = delta.get("modelCalls")
    if not isinstance(delta_model_calls, int) or isinstance(delta_model_calls, bool):
        return requested_reserve
    if delta_model_calls <= 0:
        return requested_reserve

    # --- delta.tokens defaults to 0 when absent; must be nonneg int.
    delta_tokens: Any = delta.get("tokens", 0)
    if not _valid_nonneg_int(delta_tokens):
        return requested_reserve

    # --- LIMIT fields must exist and be valid nonneg ints.
    for field in _LIMIT_FIELDS:
        if field not in budget:
            return requested_reserve
        if not _valid_nonneg_int(budget[field]):
            return requested_reserve

    max_model_calls: int = budget["maxModelCalls"]
    reserve_model_calls: int = budget["reserveModelCalls"]
    max_tokens: int = budget["maxTokens"]
    reserve_tokens: int = budget["reserveTokens"]

    # --- maxModelCalls / maxTokens strictly positive.
    if max_model_calls <= 0 or max_tokens <= 0:
        return requested_reserve

    # --- reserves must not exceed totals.
    if reserve_model_calls > max_model_calls or reserve_tokens > max_tokens:
        return requested_reserve

    # --- USED counters (default 0 when key missing).
    used: dict[str, int] = {}
    for field in _USED_FIELDS:
        val: Any = budget.get(field, 0)
        if not _valid_nonneg_int(val):
            return requested_reserve
        used[field] = val

    model_calls = used["modelCalls"]
    reserved_model_calls = used["reservedModelCalls"]
    normal_tokens = used["normalTokens"]
    tokens = used["tokens"]

    # --- Condition 1: reserve must actually be exhausted for this request.
    if reserved_model_calls + delta_model_calls <= reserve_model_calls:
        return requested_reserve

    # --- Condition 2: normal model-call capacity sufficient.
    if model_calls + delta_model_calls > max_model_calls - reserve_model_calls:
        return requested_reserve

    # --- Condition 3: combined normal + reserved + new within total.
    if model_calls + reserved_model_calls + delta_model_calls > max_model_calls:
        return requested_reserve

    # --- Condition 4: normal token capacity sufficient.
    if normal_tokens + delta_tokens > max_tokens - reserve_tokens + released_reserve_tokens(budget):
        return requested_reserve

    # --- Condition 5: total token capacity sufficient.
    if tokens + delta_tokens > max_tokens:
        return requested_reserve

    # All conditions satisfied – advise normal pool.
    return False
