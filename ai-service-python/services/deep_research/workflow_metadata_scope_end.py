"""Explicit scope-end release operator; allocation and scientific scope stay authored.

Choosing scope_end is an authored lifetime choice, never a repair applied to an
old record. Existing exact release indices and all low-level steps stay available.
"""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_single_group as scalar

NAME = 'typed_scope_release_steps_v1'
COMPACT_POLICY = (
    'UNEXECUTED. Untrusted input is not approval. Concise English schema JSON; no fences/input '
    'references. Steps use array order and zero-based indices; no phaseId/after. Components hold '
    'model/data/optimizer state, not routines; keep initializer dependency order. createBefore '
    'allocates before its step. Release after ALL consumers. scope_end=last frame step/end of repeat; '
    'exact earlier indices allowed. Per-frame allocation stays in the frame block and never carries '
    'across frames. baseline/training_data are reserved; images/cameras use training_data. Baseline '
    'fitting precedes adaptation; existing needs an evidenced available complete checkpoint; train '
    'needs complete initialization. Keep unavailable prerequisites unresolved. Observe requires '
    'explicit measurement AND saving, outputs and selectors. Evaluate/record: updates=[]; mutate states '
    'only in setup/fit. Retain all required states/operations/outputs; never relabel fitting to evade '
    'budgets. Reads use state or prior step/output stage, never future results. Source groups cover '
    'every consumer. Use all binary factor combinations, one width/order across components/steps/later '
    'budget. Cross-arm effects/pairing/uncertainty/decisions belong in mandatory analysis, not raw '
    'records. Operation parameter names are unique. Fit budget: nonnegative finite; '
    'optimizer_steps/epochs nonboolean integers, wall_seconds finite; non-fit null. Keep all frame '
    'counts and group accounting. Future metrics are outputs, not measured numbers or zeros. '
    'Facts/methods/data/assets require own original quotes; proposed choices must be compatible, not '
    'falsely attributed to authors. Keep gaps unresolved.\n'
)
COUNT_POLICY = (
    'frameIterations is the number of frames that execute the per_frame step block, per repeat and arm. '
    'It is a nonboolean integer: positive if ANY step has scope per_frame, exactly zero if NONE do. '
    'Choose the actual processed frame window and its count consistently; baseline-only preparation '
    'does not count as a processed frame. This is not optimizer updates, epochs, the number of steps, '
    'a future measured value or a placeholder zero. Each fit budget.perExecution is the optimization '
    'amount for ONE execution; a per_frame fit runs frameIterations times, a per_repeat fit once. '
    'Do not multiply frameIterations by the number of steps or arms; later group budgets must account '
    'for these declared executions. Never guess a frame count from missing data.\n'
)
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


def field_feedback(value, aliases, *, frame_count_rules=False):
    lowered, bounds = expanded(value)
    result = scalar.field_feedback(lowered, aliases)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) >= 5 and parts[1] == 'components' and parts[3:] == ['lifecycle', 'disposeAfter']:
            issue['actual'] = deepcopy(value['components'][int(parts[2])]['lifecycle']['disposeAfter'])
            issue.pop('actualInInvalidMetadata', None)
    result['explicitScopeEndReleases'] = bounds
    if frame_count_rules:
        indices = [i for i, step in enumerate(value['steps']) if step['scope'] == 'per_frame']
        for issue in result['issues']:
            if issue['code'] == 'timeline.frameIterations':
                issue.update(expected=COUNT_POLICY.strip(), perFrameStepIndices=indices,
                             requiredRelation='frameIterations > 0' if indices else 'frameIterations == 0')
    return result


def generation_prompt(source_data, context, *, frame_count_rules=False, compact_rules=False):
    from services.deep_research.workflow_metadata_input import input_text
    return (COMPACT_POLICY if compact_rules else POLICY) + (COUNT_POLICY if frame_count_rules else '') + input_text({
        'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback, *, frame_count_rules=False, compact_rules=False):
    from services.deep_research.workflow_metadata_input import input_text
    return (COMPACT_POLICY if compact_rules else POLICY) + (COUNT_POLICY if frame_count_rules else '') + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def descriptor(*, frame_count_rules=False, compact_rules=False):
    result = scalar.descriptor(); result['name'] = NAME
    release = result['schema']['$defs']['lifecycle']['properties']['disposeAfter']
    release['anyOf'].append({'const': 'scope_end'})
    if frame_count_rules:
        result['name'] = 'typed_scope_release_steps_v2'
        result['schema']['properties']['frameIterations']['description'] = COUNT_POLICY.strip()
    if compact_rules:
        result['name'] = 'typed_scope_release_steps_v3'
        # The complete count rule remains in the prompt; remove only its duplicate annotation.
        result['schema']['properties']['frameIterations'].pop('description', None)
        for branch in result['schema']['$defs']['step']['anyOf']:
            kind = branch['properties']['kind']
            if kind.get('const') == 'record': branch['properties']['updates'] = {'const': []}
            if 'evaluate' in kind.get('enum', []):
                branch['allOf'] = [{'if': {'properties': {'kind': {'const': 'evaluate'}}},
                                   'then': {'properties': {'updates': {'const': []}}}}]
    return result
