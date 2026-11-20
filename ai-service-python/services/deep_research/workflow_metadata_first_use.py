"""Authored first-use allocation mode; existing coordinates never reinterpreted."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_bounded_schema as previous
from services.deep_research.workflow_metadata_reference_context import POLICY as OLD_POLICY

FIRST_USE = 'before_first_use'
POLICY = OLD_POLICY.replace(
    'createInScope indexes frame steps for per_frame, all steps for per_repeat; allocate before that step.',
    'createInScope is before_first_use OR an explicit scope-local index. before_first_use allocates '
    'before the first declared state read/update; repeat resources used in frames start before the frame block.')
POLICY += ('Save frame results inside the frame block; pairing/aggregation belongs in later analysis of saved '
           'records. A per_repeat step cannot directly read a temporary per_frame value.\n')


def _uses(step, component_id):
    reads = step.get('reads'); updates = step.get('updates')
    return ((isinstance(reads, list) and any(isinstance(r, dict) and r.get('state') == component_id for r in reads))
            or isinstance(updates, list) and component_id in updates)


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('components'), list):
        raise ValueError('Incomplete first-use metadata')
    steps = result.get('steps')
    if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
        raise ValueError('Invalid authored steps')
    frames = [i for i, step in enumerate(steps) if step.get('scope') == 'per_frame']
    issues = []; resolutions = {}
    for index, component in enumerate(result['components']):
        if not isinstance(component, dict) or not isinstance(component.get('lifecycle'), dict):
            raise ValueError('Incomplete authored component')
        life = component['lifecycle']
        if life.get('createInScope') != FIRST_USE: continue
        component_id = component.get('componentId'); scope = life.get('scope')
        uses = [i for i, step in enumerate(steps) if isinstance(component_id, str) and component_id.strip()
                and _uses(step, component_id)]
        reason = None
        if scope not in ('per_frame', 'per_repeat'): reason = 'invalid_scope'
        elif not uses: reason = 'no_declared_state_use'
        elif scope == 'per_frame' and steps[uses[0]].get('scope') != 'per_frame': reason = 'first_use_outside_frame'
        if reason:
            issues.append({'code': 'allocation.first_use', 'path': f'/components/{index}/lifecycle/createInScope',
                'actual': FIRST_USE, 'componentId': deepcopy(component_id), 'reason': reason,
                'expected': 'declare a compatible state read/update and scope, or explicitly choose an earlier scope-local index'})
            continue
        boundary = uses[0]
        if scope == 'per_repeat' and steps[boundary].get('scope') == 'per_frame': boundary = frames[0]
        coordinates = frames if scope == 'per_frame' else list(range(len(steps)))
        local = coordinates.index(boundary)
        life['createInScope'] = local
        resolutions[index] = {'firstUseStepIndex': uses[0], 'allocationStepIndex': boundary,
                              'resolvedScopeIndex': local}
    return result, issues, resolutions


def complete_scaffolding(value):
    try: return previous.complete_scaffolding(expanded(value)[0])
    except (TypeError, ValueError, RecursionError): return False


def decode(value):
    lowered, issues, _ = expanded(value)
    if issues: raise ValueError('Unresolved authored first-use allocation')
    return previous.decode(lowered)


def field_feedback(value, aliases):
    lowered, issues, resolutions = expanded(value)
    if issues: return {'issues': issues, 'scientificApproval': False, 'authoredValuesPreserved': True}
    result = previous.field_feedback(lowered, aliases)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) == 5 and parts[1] == 'components' and parts[3:] == ['lifecycle', 'createInScope']:
            index = int(parts[2])
            if index in resolutions:
                issue.update(actual=FIRST_USE, **resolutions[index]); issue.pop('actualInInvalidMetadata', None)
    return result


def descriptor():
    result = previous.descriptor(); result['name'] = 'metadata_steps_v25'
    schema = result['schema']; ref = schema['properties']['components']['items']['properties']['lifecycle']['$ref']
    lifecycle = schema['$defs'][ref.removeprefix('#/$defs/')]
    original = lifecycle['properties']['createInScope']
    lifecycle['properties']['createInScope'] = {'anyOf': [deepcopy(original), {'const': FIRST_USE}]}
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return POLICY + COUNT_POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return POLICY + COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})
