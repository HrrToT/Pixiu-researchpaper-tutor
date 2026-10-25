"""Authored scope entrance allocation, without changing legacy exact indices.

An entrance is an explicit placement choice, not permission to move an invalid
integer allocation. Downstream dependency, group and lifecycle checks still apply.
This grammar is deliberately separate from the active scope-end contracts.
"""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_scope_end as release

NAME = 'typed_scope_boundaries_steps_v1'
POLICY = release.COMPACT_POLICY + (
    'createBefore may be "scope_start": allocate before the first step of the '
    'component\'s declared scope (repeat entrance or first per_frame step). This does not choose '
    'the scope or provide missing dependencies. Use an exact later step index '
    'when initialization needs earlier step outputs. A missing frame block has '
    'no frame entrance.\n'
)


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('components'), list):
        raise ValueError('Incomplete scope entrance metadata')
    steps = result.get('steps')
    if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
        raise ValueError('Invalid authored steps')
    bounds = []
    for i, component in enumerate(result['components']):
        if not isinstance(component, dict) or not isinstance(component.get('lifecycle'), dict):
            raise ValueError('Incomplete lifecycle')
        life = component['lifecycle']
        if life.get('createBefore') != 'scope_start':
            continue
        scope = life.get('scope')
        if scope not in ('per_repeat', 'per_frame'):
            raise ValueError('Unknown authored lifetime scope')
        indices = ([0] if steps else []) if scope == 'per_repeat' else [
            j for j, step in enumerate(steps) if step.get('scope') == scope]
        if not indices:
            raise ValueError('Authored scope has no declared entrance')
        boundary = indices[0]
        life['createBefore'] = boundary
        bounds.append({'componentIndex': i, 'componentId': component.get('componentId'),
                       'scope': scope, 'createBefore': boundary})
    return result, bounds


def complete_scaffolding(value):
    try:
        return release.complete_scaffolding(expanded(value)[0])
    except (ValueError, TypeError, RecursionError):
        return False


def decode(value):
    return release.decode(expanded(value)[0])


def field_feedback(value, aliases):
    lowered, bounds = expanded(value)
    result = release.field_feedback(lowered, aliases, frame_count_rules=True)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) == 5 and parts[1] == 'components' and parts[3:] == ['lifecycle', 'createBefore']:
            issue['actual'] = deepcopy(value['components'][int(parts[2])]['lifecycle']['createBefore'])
            issue.pop('actualInInvalidMetadata', None)
    result['explicitScopeStartAllocations'] = bounds
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
    life = result['schema']['$defs']['lifecycle']['properties']
    life['createBefore'] = {'anyOf': [life['createBefore'], {'const': 'scope_start'}]}
    return result
