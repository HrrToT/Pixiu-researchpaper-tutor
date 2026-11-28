"""Metric-scope grounding for deep-research briefs.

Structural validation only: each requested metric domain must be
accompanied by an *exact* excerpt drawn from the user question.  This
does **not** assess semantic relevance; a downstream whole-question
completeness audit remains required.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

SHARED_SCOPE_MARKER = "sharedExperimentMetricScopeVersion"
_CANONICAL_ORDER: tuple = ("quality", "speed", "storage")
_SHARED_ORDER = (*_CANONICAL_ORDER, "memory")
_DEVICE_MEMORY = re.compile(r'显存|\b(?:VRAM|(?:GPU|device) memory)\b', re.I)
_PERSISTENT_STORAGE = re.compile(r'磁盘|存储|文件大小|模型体积|\b(?:disk|storage|checkpoint size|file size)\b', re.I)

_PROTOCOL_REQUIREMENTS: Dict[str, str] = {
    "quality": (
        "For each quality metric, state its direction (higher-is-better or "
        "lower-is-better) and specify the image/view aggregation level; do "
        "not average metrics that are incompatible in scale or meaning."
    ),
    "speed": (
        "Report the device, resolution, warmup procedure, synchronization "
        "method, timed region, and number of repetitions for every speed "
        "measurement."
    ),
    "storage": (
        "List the included files or model representation, and state the "
        "accounting boundaries and units used for the storage measurement."
    ),
    "memory": (
        "Specify device and allocator, peak allocated or reserved memory, the complete "
        "measurement interval, synchronization, and how incomplete or OOM runs are recorded."
    ),
}


def _all_domains() -> List[str]:
    """Return every allowed domain in canonical order (fresh list)."""
    return list(_CANONICAL_ORDER)


def grounded_metric_domains(raw: Any, question: Any, *, shared_scope=False) -> List[str]:
    """Ground each selected domain in a literal excerpt from the question."""
    order = _SHARED_ORDER if shared_scope else _CANONICAL_ORDER
    fallback = [] if shared_scope else _all_domains()
    if not isinstance(question, str) or not question or not isinstance(raw, list) or not raw:
        return fallback

    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            return fallback
        domain = entry.get("domain")
        excerpt = entry.get("requestExcerpt")
        if not isinstance(domain, str) or domain not in order:
            return fallback
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in question:
            return fallback
        if (shared_scope and domain == "storage" and _DEVICE_MEMORY.search(excerpt)
                and not _PERSISTENT_STORAGE.search(excerpt)):
            domain = "memory"
        if domain in seen and not shared_scope:
            return fallback
        seen.add(domain)

    return [domain for domain in order if domain in seen]


def metric_protocol_requirements(domains: Any = None) -> Dict[str, str]:
    """Map each selected domain to its English protocol requirement.

    *domains* must be a list of known, unique domain strings to select a
    subset (returned in canonical order).  ``None``, an empty list, or any
    malformed value falls back to all three domains.
    """
    if domains is None or not isinstance(domains, list) or len(domains) == 0:
        selected = list(_CANONICAL_ORDER)
    else:
        seen: set = set()
        valid = True
        for d in domains:
            if not isinstance(d, str) or d not in _SHARED_ORDER or d in seen:
                valid = False
                break
            seen.add(d)
        if not valid or not seen:
            selected = list(_CANONICAL_ORDER)
        else:
            selected = [d for d in _SHARED_ORDER if d in seen]

    return {d: _PROTOCOL_REQUIREMENTS[d] for d in selected}
