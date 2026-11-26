"""Reject explicit contradictions before spending a scientific review call."""

import re

MARKER = 'sharedExperimentProtocolPrecheckVersion'

_MODULO = re.compile(r'\bi\s*(?:mod\s*|%\s*)(\d{1,3})\s*={1,2}\s*(\d{1,3})\b', re.I)
_COUNT = re.compile(
    r'(?:\b(?:evaluation|eval|test|held.out)\s+(?:image\s+)?count\s*(?:equals?|=)'
    r'|(?:评估|测试)(?:图像)?(?:数|数量)\s*(?:应)?(?:等于|为|=))\s*'
    r'(floor|ceil)\s*\(\s*N\s*/\s*(\d{1,3})\s*\)', re.I)
_ORIGINS = (
    re.compile(r'\b(?:zero|0)[ -]based\b|\bi\s+(?:starts?|begins?)\s+(?:at|from)\s+0\b|从\s*0\s*开始', re.I),
    re.compile(r'\b(?:one|1)[ -]based\b|\bi\s+(?:starts?|begins?)\s+(?:at|from)\s+1\b|从\s*1\s*开始', re.I),
)
_CONDITIONAL = re.compile(r'\b(?:if|unless|when|assuming|divisible|multiple|padding|padded)\b|整除|倍数|补齐|如果|若', re.I)
_ARM_UNIT = re.compile(
    r'(?:each|one|a|every)\s+(?:trained\s+)?(?:arm|treatment group)'
    r'(?:\s+(?:on|in|for)\s+(?:one|a|each)\s+(?:selected\s+)?(?:scene|dataset|block))?'
    r'\s+(?:is|counts as|constitutes)\s+(?:an?|one)\s+independent\s+(?:replicate|unit|sample)\b'
    r'|(?:每|单|一)(?:个|条)?(?:实验臂|实验组|处理组)\s*(?:是|作为|计作)\s*(?:一个)?独立(?:重复)?(?:单位|单元|样本)', re.I)
_QUOTED_OR_REJECTED = re.compile(r'\b(?:not|never|incorrect\w*|wrong\w*|mislead\w*|avoid)\b|不是|不应|不能|错误|避免', re.I)


def enabled(record):
    return type(record.get(MARKER)) is int and record[MARKER] == 1


def _split_issue(data):
    text = ' '.join(data['splitPrecheck'].split())
    moduli = list(_MODULO.finditer(text))
    counts = list(_COUNT.finditer(text))
    if len(moduli) != 1 or len(counts) != 1 or _CONDITIONAL.search(text):
        return None
    period, residue = map(int, moduli[0].groups())
    function, divisor = counts[0].groups()
    if period < 2 or not 0 <= residue < period or int(divisor) != period:
        return None
    scope = ' '.join(data[key] for key in ('trainingSplit', 'evaluationSplit', 'splitPrecheck'))
    origins = [origin for origin, pattern in enumerate(_ORIGINS) if pattern.search(scope)]
    issue = {'path': '/data/splitPrecheck'}
    if not origins:
        return {**issue, 'reason': 'split_index_origin_missing', 'period': period, 'residue': residue}
    if len(origins) != 1:
        return {**issue, 'reason': 'split_index_origin_conflicting'}
    origin = origins[0]
    # After one full period, both counts increase by one. A mismatch in a
    # partial period therefore also occurs for larger, nonempty datasets.
    first = (residue - origin) % period
    for n in range(1, period):
        actual = (n + period - first - 1) // period
        claimed = (n + period - 1) // period if function.lower() == 'ceil' else n // period
        if actual != claimed:
            return {**issue, 'reason': 'split_holdout_count_mismatch',
                    'exampleImageCount': n + period, 'selected': actual + 1, 'claimed': claimed + 1}
    return None


def detect(proposal):
    """Flag literal assertions in known forms. Ambiguous text still needs review."""
    data = proposal['data']
    split = _split_issue(data)
    issues = [split] if split else []
    unit = ' '.join(data['independentUnit'].split())
    if _ARM_UNIT.search(unit) and not _QUOTED_OR_REJECTED.search(unit):
        issues.append({'path': '/data/independentUnit', 'reason': 'paired_arm_is_not_independent_replicate'})
    return issues
