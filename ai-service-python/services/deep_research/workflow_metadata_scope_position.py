"""Explicit scope-local allocation coordinates for newly authored metadata.

This is a new wire, not reinterpretation or repair of old createBefore values.
All other step references and release coordinates retain their global meaning.
"""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_scope_end as release

NAME = 'typed_scope_positions_steps_v1'
FIELD = 'createInScope'
POLICY = release.COMPACT_POLICY.replace(
    'createBefore allocates before its step.',
    'createInScope: 0-based among frame steps for per_frame, all steps for '
    'per_repeat; allocation precedes that step. Other indices global.'
)


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('components'), list):
        raise ValueError('Incomplete scope position metadata')
    steps = result.get('steps')
    if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
        raise ValueError('Invalid authored steps')
    issues = []
    for i, component in enumerate(result['components']):
        if not isinstance(component, dict) or not isinstance(component.get('lifecycle'), dict):
            raise ValueError('Incomplete lifecycle')
        life = component['lifecycle']
        if set(life) != {'scope', FIELD, 'disposeAfter'}:
            raise ValueError('Ambiguous or missing scoped allocation coordinate')
        scope = life['scope']; local = life.pop(FIELD)
        indices = (list(range(len(steps))) if scope == 'per_repeat' else
                   [j for j, step in enumerate(steps) if step.get('scope') == 'per_frame']
                   if scope == 'per_frame' else [])
        if type(local) is int and 0 <= local < len(indices):
            life['createBefore'] = indices[local]
        else:
            # Retain the invalid leaf for structural eligibility only. decode()
            # refuses it before any downstream semantic use; no fallback index.
            life['createBefore'] = local
            issues.append({'code': 'scope_position.allocation',
                'path': f'/components/{i}/lifecycle/{FIELD}', 'actual': deepcopy(local),
                'expected': 'nonboolean integer indexing the declared scope steps',
                'scope': deepcopy(scope), 'availableGlobalStepIndices': indices})
    return result, issues


def complete_scaffolding(value):
    try:
        return release.complete_scaffolding(expanded(value)[0])
    except (ValueError, TypeError, RecursionError):
        return False


def decode(value):
    lowered, issues = expanded(value)
    if issues:
        raise ValueError('Invalid scope-local allocation coordinate')
    return release.decode(lowered)


def field_feedback(value, aliases):
    lowered, issues = expanded(value)
    if issues:
        return {'issues': issues, 'scientificApproval': False}
    result = release.field_feedback(lowered, aliases, frame_count_rules=True)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) == 5 and parts[1] == 'components' and parts[3:] == ['lifecycle', 'createBefore']:
            component = int(parts[2])
            issue['path'] = f'/components/{component}/lifecycle/{FIELD}'
            issue['actual'] = deepcopy(value['components'][component]['lifecycle'][FIELD])
            issue.pop('actualInInvalidMetadata', None)
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + release.COUNT_POLICY + input_text({
        'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + release.COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def descriptor():
    result = release.descriptor(frame_count_rules=True, compact_rules=True)
    result['name'] = NAME
    lifecycle = result['schema']['$defs']['lifecycle']
    lifecycle['properties'][FIELD] = lifecycle['properties'].pop('createBefore')
    lifecycle['required'] = [FIELD if key == 'createBefore' else key for key in lifecycle['required']]
    return result
