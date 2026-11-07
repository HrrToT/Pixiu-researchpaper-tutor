"""Compile authored symbolic wiring; never choose scientific values or sources."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_observation_boundary as previous
from services.deep_research import workflow_metadata_result_refs as refs

ALL_MEASUREMENTS = 'all_measurements'
POLICY = previous.CONCISE_POLICY.replace(
    'Global step indices identify producers. Reads: {state,selector} for reserved/declared states, '
    '{stepIndex,outputId,selector} for primitive/measurement results, '
    '{stepIndex,savedOutputId,selector} for observe.recording results; no future reads.',
    'Reads: {state,selector} for reserved/declared states or {result,selector} for an exact '
    'declared result name. Referenced result names must be unique across ALL operation, measurement '
    'and recording outputs. The compiler resolves the producer; never supply stepIndex or savedOutputId. '
    'No future or cross-arm reads.')
POLICY = POLICY.replace(
    'Observe measurement produces outputs; recording explicitly selects every measurement result, then produces recording.outputs.',
    'Observe measurement produces outputs. recording.inputs may be "all_measurements" to save each '
    'declared measurement output in full, or explicit [{outputId,selector},...] covering every output. '
    'This directive selects complete outputs, never computes missing metrics. recording.outputs '
    'are separate named saved results; declare the actual measurement operations before recording.')


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('steps'), list):
        raise ValueError('Incomplete symbolic metadata')
    symbols = {}
    for index, step in enumerate(result['steps']):
        if not isinstance(step, dict): raise ValueError('Invalid authored step')
        blocks = [(step.get('outputs'), 'outputId')]
        if step.get('kind') == 'observe' and isinstance(step.get('recording'), dict):
            blocks.append((step['recording'].get('outputs'), 'savedOutputId'))
        for outputs, field in blocks:
            if not isinstance(outputs, list): continue
            for name in outputs:
                if isinstance(name, str) and name.strip():
                    symbols.setdefault(name, []).append((index, field))
    issues = []
    for index, step in enumerate(result['steps']):
        reads = step.get('reads')
        if isinstance(reads, list):
            for offset, read in enumerate(reads):
                path = f'/steps/{index}/reads/{offset}'
                if isinstance(read, dict) and set(read) == {'state', 'selector'}: continue
                if not isinstance(read, dict) or set(read) != {'result', 'selector'}:
                    issues.append({'code': 'symbol.fields', 'path': path,
                                   'expected': '{state,selector} or {result,selector}; no producer indices'})
                    continue
                name = read['result']
                choices = symbols.get(name, []) if isinstance(name, str) else []
                if len(choices) != 1:
                    issues.append({'code': 'symbol.ambiguous' if choices else 'symbol.missing',
                        'path': path+'/result', 'actual': deepcopy(name),
                        'producers': [{'stepIndex': i, 'field': f} for i,f in choices],
                        'expected': 'one exact globally unique declared output name; never guess a producer'})
                    continue
                producer, field = choices[0]
                reads[offset] = {'stepIndex': producer, field: name, 'selector': deepcopy(read['selector'])}
        recording = step.get('recording')
        if step.get('kind') == 'observe' and isinstance(recording, dict) and recording.get('inputs') == ALL_MEASUREMENTS:
            outputs = step.get('outputs')
            if (not isinstance(outputs, list) or not outputs
                    or any(not isinstance(x, str) or not x.strip() for x in outputs)
                    or len(set(outputs)) != len(outputs)):
                issues.append({'code': 'symbol.measurements', 'path': f'/steps/{index}/outputs',
                               'expected': 'nonempty unique declared outputs before saving all measurements'})
            else:
                recording['inputs'] = [{'outputId': name, 'selector': 'all'} for name in outputs]
    return result, issues


def complete_scaffolding(value):
    try: return refs.complete_scaffolding(expanded(value)[0])
    except (TypeError, ValueError, RecursionError, AttributeError): return False


def decode(value):
    lowered, issues = expanded(value)
    if issues: raise ValueError('Unresolved symbolic result')
    return refs.decode(lowered)


def field_feedback(value, aliases):
    lowered, issues = expanded(value)
    if issues: return {'issues': issues, 'scientificApproval': False, 'authoredValuesPreserved': True}
    result = previous.complete_field_feedback(lowered, aliases)
    # Compiler-created leaves have no authored pointer. Point back to the
    # complete instruction, preserving downstream group/time/scope diagnostics.
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) >= 5 and parts[1] == 'steps':
            step = value['steps'][int(parts[2])]
            if parts[3] == 'reads':
                read = step['reads'][int(parts[4])]
                if isinstance(read, dict) and 'result' in read:
                    issue['path'] = '/'.join(parts[:5]); issue['actual'] = deepcopy(read)
                    issue.pop('actualInInvalidMetadata', None); issue['actualPresent'] = True
            elif parts[3:5] == ['recording', 'inputs'] and step['recording']['inputs'] == ALL_MEASUREMENTS:
                issue['path'] = '/'.join(parts[:5]); issue['actual'] = ALL_MEASUREMENTS
                issue.pop('actualInInvalidMetadata', None); issue['actualPresent'] = True
    return result


def descriptor():
    result = previous.descriptor(); result['name'] = 'metadata_symbolic_results_v1'
    changed = [0, 0]
    def visit(node):
        if isinstance(node, dict):
            branches = node.get('anyOf')
            if isinstance(branches, list) and any(set(b.get('properties', {})) == {'stepIndex','outputId','selector'} for b in branches):
                state = next(deepcopy(b) for b in branches if set(b.get('properties', {})) == {'state','selector'})
                symbolic = deepcopy(state); symbolic['properties']['result'] = symbolic['properties'].pop('state')
                symbolic['required'] = ['result','selector']; node['anyOf'] = [state, symbolic]; changed[0] += 1
            props = node.get('properties', {})
            if set(props) == {'inputs','action','outputs'}:
                props['inputs'] = {'anyOf': [{'const': ALL_MEASUREMENTS}, props['inputs']]}; changed[1] += 1
            for item in list(node.values()): visit(item)
        elif isinstance(node, list):
            for item in node: visit(item)
    visit(result['schema'])
    if changed != [1,1]: raise ValueError('Symbolic metadata schema shape changed')
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})
