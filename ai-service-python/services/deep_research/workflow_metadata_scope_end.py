"""Explicit scope-end release operator; allocation and scientific scope stay authored.

Choosing scope_end is an authored lifetime choice, never a repair applied to an
old record. Existing exact release indices and all low-level steps stay available.
"""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_single_group as scalar

NAME = 'typed_scope_release_steps_v1'
POLICY = scalar.POLICY.replace(scalar.NAME, NAME).replace(
    'disposeAfter (step index or null):',
    'disposeAfter (step index, null, or "scope_end"):').replace(
    'Per-frame state starts in the frame block, needs disposal, never carries to later frames.',
    'Choose disposeAfter:"scope_end" to retain state through its entire authored scope: '
    'per_frame releases after the last per_frame step, per_repeat after the repeat. '
    'An exact step index remains available for intentional earlier release, but must follow ALL consumers. '
    'Allocation createBefore and lifetime scope remain explicit choices. '
    'Per-frame state starts in the frame block, needs disposal, never carries to later frames.')


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('components'), list):
        raise ValueError('Incomplete scope release metadata')
    sequence = result.get('steps')
    if not isinstance(sequence, list) or any(not isinstance(s, dict) for s in sequence):
        raise ValueError('Invalid authored steps')
    bounds = []
    for i, component in enumerate(result['components']):
        if not isinstance(component, dict) or not isinstance(component.get('lifecycle'), dict):
            raise ValueError('Incomplete lifecycle')
        life = component['lifecycle']
        if life.get('disposeAfter') != 'scope_end': continue
        scope = life.get('scope')
        if scope == 'per_repeat': boundary = None
        elif scope == 'per_frame':
            frames = [j for j, step in enumerate(sequence) if step.get('scope') == 'per_frame']
            if not frames: raise ValueError('Frame scope has no declared frame block')
            boundary = frames[-1]
        else: raise ValueError('Unknown authored lifetime scope')
        life['disposeAfter'] = boundary
        bounds.append({'componentIndex': i, 'componentId': component.get('componentId'),
                       'scope': scope, 'disposeAfter': boundary})
    return result, bounds


def complete_scaffolding(value):
    try: return scalar.complete_scaffolding(expanded(value)[0])
    except (ValueError, TypeError, RecursionError): return False


def decode(value): return scalar.decode(expanded(value)[0])


def field_feedback(value, aliases):
    lowered, bounds = expanded(value)
    result = scalar.field_feedback(lowered, aliases)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) >= 5 and parts[1] == 'components' and parts[3:] == ['lifecycle', 'disposeAfter']:
            issue['actual'] = deepcopy(value['components'][int(parts[2])]['lifecycle']['disposeAfter'])
            issue.pop('actualInInvalidMetadata', None)
    result['explicitScopeEndReleases'] = bounds
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def descriptor():
    result = scalar.descriptor(); result['name'] = NAME
    release = result['schema']['$defs']['lifecycle']['properties']['disposeAfter']
    release['anyOf'].append({'const': 'scope_end'})
    return result
