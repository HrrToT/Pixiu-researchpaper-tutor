"""Reject explicit contradictions before spending a scientific review call."""

import re

MARKER = 'sharedExperimentProtocolPrecheckVersion'
_RECIPE_FIELDS = ('training_loss', 'renderer_convention', 'sh_convention')
_PIN_FIELDS = ('fit_implementation_pin', 'fit_entrypoint', 'fit_config')
RECIPE_PARAMETER_NAMES = frozenset(('fit_recipe_state', *_RECIPE_FIELDS, *_PIN_FIELDS))
_CONTENT_PIN = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', re.I)

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
    return type(record.get(MARKER)) is int and record[MARKER] in (1, 2)


def fit_recipe_requested(record):
    if type(record.get(MARKER)) is not int or record[MARKER] != 2:
        return False
    from services.deep_research.experiment_protocol_sources import DENSIFICATION, roles
    return any(DENSIFICATION in roles(obligation, densification=True)
               for item in record.get('state', {}).get('plan', [])
               for obligation in item['obligations'])


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


def _choice_parameters(step):
    """Duplicate parameter names cannot establish an unambiguous recipe."""
    parameters = step['operation']['parameters']
    names = [row['name'] for row in parameters]
    if len(names) != len(set(names)):
        return {}
    return {row['name']: row['value'].strip() for row in parameters
            if row['type'] == 'choice' and isinstance(row['value'], str) and row['value'].strip()}


def _recipe_candidates(proposal, fits):
    common_reads = set.intersection(*(set(step['reads']) for step in fits))
    states = {row['id']: row for row in proposal['states']}
    for index, step in enumerate(proposal['steps']):
        if (step['kind'], step['scope'], step['dataUse']) != ('prepare', 'shared', 'training'):
            continue
        candidates = [states[sid] for sid in step['creates'] if sid in common_reads
                      and states[sid]['fixed'] and states[sid]['persisted']
                      and states[sid]['scope'] == 'shared'
                      and states[sid]['source'] == {'kind': 'step', 'id': step['id']}]
        if candidates:
            yield index, step, candidates


def existing_recipe_slots(proposal):
    """Find shared states which can carry the recipe without rewiring either fit."""
    fits = [step for step in proposal['steps'] if step['kind'] == 'fit' and step['dataUse'] == 'training']
    return [{
        'parameterPath': f'/steps/{index}/operation/parameters',
        'stepId': step['id'],
        'existingOperation': step['operation'],
        'stateChoices': [{k: state[k] for k in ('id', 'meaning', 'representation')} for state in candidates],
    } for index, step, candidates in _recipe_candidates(proposal, fits)] if fits else []


def _fit_recipe_issue(proposal):
    fits = [step for step in proposal['steps'] if step['kind'] == 'fit' and step['dataUse'] == 'training']
    if not fits:
        return None
    for _, step, candidates in _recipe_candidates(proposal, fits):
        fields = _choice_parameters(step)
        recipe = fields.get('fit_recipe_state')
        if recipe not in {row['id'] for row in candidates}:
            continue
        if all(key in fields for key in _RECIPE_FIELDS):
            return None
        if (all(key in fields for key in _PIN_FIELDS)
                and _CONTENT_PIN.fullmatch(fields['fit_implementation_pin'])):
            return None
    return {
        'path': '/steps', 'reason': 'shared_training_recipe_missing',
        'trainingFitStepIds': [step['id'] for step in fits],
        'explicitChoiceParameters': list(_RECIPE_FIELDS),
        'pinnedImplementationChoiceParameters': list(_PIN_FIELDS),
        'binding': 'Create a fixed persisted shared state in training prep. Set fit_recipe_state to its ID; every training fit reads it.',
    }


def detect(proposal, *, require_fit_recipe=False):
    """Flag explicit contradictions and missing execution bindings before scientific review."""
    data = proposal['data']
    split = _split_issue(data)
    issues = [split] if split else []
    unit = ' '.join(data['independentUnit'].split())
    if _ARM_UNIT.search(unit) and not _QUOTED_OR_REJECTED.search(unit):
        issues.append({'path': '/data/independentUnit', 'reason': 'paired_arm_is_not_independent_replicate'})
    if require_fit_recipe:
        recipe = _fit_recipe_issue(proposal)
        if recipe:
            issues.append(recipe)
    return issues
