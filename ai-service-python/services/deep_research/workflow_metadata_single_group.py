"""Explicit scalar ownership for operations that execute in exactly one arm.

No arm is selected or split here: the author's single group is preserved.
Contract13 and historical records retain their original representation.
"""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_steps as steps

NAME = 'typed_single_group_steps_v1'
SINGLE = ('observe', 'record')
POLICY = steps.POLICY.replace('typed_workflow_steps_v1', NAME).replace(
    'groups:[one binary ID]', 'group:one binary ID string').replace(
    'each record belongs to one group with per_group execution.',
    'record replaces groups with group (one binary ID string), with per_group execution.').replace(
    'Binary group IDs enumerate all factor',
    'Observe/record use only scalar group, never groups; other steps keep groups arrays. '
    'Binary group IDs enumerate all factor')


def expanded(value):
    value = deepcopy(value)
    if not isinstance(value, dict) or not isinstance(value.get('steps'), list):
        raise ValueError('Incomplete scalar ownership metadata')
    for step in value['steps']:
        if not isinstance(step, dict): raise ValueError('Invalid step')
        if step.get('kind') in SINGLE:
            if 'group' not in step or 'groups' in step:
                raise ValueError('Explicit single binary group string required')
            # Invalid leaf values remain invalid for the original validators;
            # retaining them permits precise one-shot correction, never coercion.
            step['groups'] = [step.pop('group')]
    return value


def complete_scaffolding(value):
    try: return steps.complete_scaffolding(expanded(value))
    except (ValueError, TypeError, RecursionError): return False


def decode(value): return steps.decode(expanded(value))


def field_feedback(value, aliases):
    result = steps.field_feedback(expanded(value), aliases)
    for issue in result['issues']:
        path = issue['path'].split('/')
        if len(path) >= 4 and path[1] == 'steps' and path[3] == 'groups':
            step = value['steps'][int(path[2])]
            if step['kind'] in SINGLE:
                issue['path'] = '/steps/' + path[2] + '/group'
                issue['actual'] = step['group']
                issue.pop('actualInInvalidMetadata', None)
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def descriptor():
    result = steps.descriptor(); result['name'] = NAME
    for branch in result['schema']['$defs']['step']['anyOf']:
        if branch['properties']['kind'].get('const') in SINGLE:
            group = branch['properties'].pop('groups')['items']
            branch['properties']['group'] = group
            branch['required'].remove('groups'); branch['required'].append('group')
    return result
