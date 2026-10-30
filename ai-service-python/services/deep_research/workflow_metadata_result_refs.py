"""Authored result IDs determine wiring; no guessed producer, selector or stage."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_first_use as previous

POLICY = previous.POLICY.replace(
    'use {stepIndex,outputStage,outputId,selector}. outputStage=operation for primitives, '
    'measurement|record for observe.',
    'use {stepIndex,outputId,selector}; observe.recording outputs use '
    '{stepIndex,savedOutputId,selector}. Never author outputStage; the declared producer/output determines it.')


def expanded(value):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('steps'), list):
        raise ValueError('Incomplete result-reference metadata')
    steps = result['steps']; issues = []
    for i, consumer in enumerate(steps):
        if not isinstance(consumer, dict): raise ValueError('Invalid authored step')
        reads = consumer.get('reads')
        if not isinstance(reads, list): continue  # original validator diagnoses the leaf
        for j, item in enumerate(reads):
            path = f'/steps/{i}/reads/{j}'
            if isinstance(item, dict) and set(item) == {'state', 'selector'}: continue
            fields = set(item) if isinstance(item, dict) else set()
            field = 'savedOutputId' if 'savedOutputId' in fields else 'outputId'
            if fields != {'stepIndex', field, 'selector'}:
                issues.append({'code': 'result_ref.fields', 'path': path,
                    'expected': '{state,selector}, {stepIndex,outputId,selector}, or {stepIndex,savedOutputId,selector}; no outputStage'})
                continue
            index = item['stepIndex']
            if type(index) is not int or not 0 <= index < len(steps):
                issues.append({'code': 'result_ref.index', 'path': path+'/stepIndex',
                    'actual': deepcopy(index), 'expected': 'exact declared producer step index; never guess/coerce'})
                continue
            producer = steps[index]
            if not isinstance(producer, dict): raise ValueError('Invalid producer step')
            kind = producer.get('kind')
            if field == 'savedOutputId':
                if kind != 'observe':
                    issues.append({'code': 'result_ref.saved_source', 'path': path+'/savedOutputId',
                        'actual': deepcopy(item[field]),
                        'expected': 'savedOutputId selects observe.recording only; primitive record exposes outputId'})
                    continue
                recording = producer.get('recording')
                outputs = recording.get('outputs') if isinstance(recording, dict) else None
                stage = 'record'
            elif kind == 'observe': outputs = producer.get('outputs'); stage = 'measurement'
            elif kind in ('setup', 'fit', 'evaluate', 'evaluate_shared', 'record'):
                outputs = producer.get('outputs'); stage = 'operation'
            else:
                issues.append({'code': 'result_ref.source_kind', 'path': path+'/stepIndex',
                    'actual': deepcopy(index), 'expected': 'a declared primitive or observe producer'})
                continue
            output = item[field]
            if not isinstance(output, str) or not output.strip() or not isinstance(outputs, list) or output not in outputs:
                issues.append({'code': 'result_ref.output', 'path': path+'/'+field,
                    'actual': deepcopy(output), 'declaredOutputs': deepcopy(outputs),
                    'expected': 'one exact output ID from the selected producer block; never invent or switch blocks'})
                continue
            reads[j] = {'stepIndex': index, 'outputStage': stage, 'outputId': output,
                        'selector': deepcopy(item['selector'])}
    return result, issues


def complete_scaffolding(value):
    try: return previous.complete_scaffolding(expanded(value)[0])
    except (TypeError, ValueError, RecursionError, AttributeError): return False


def decode(value):
    lowered, issues = expanded(value)
    if issues: raise ValueError('Unresolved result reference')
    return previous.decode(lowered)


def field_feedback(value, aliases):
    lowered, issues = expanded(value)
    if issues: return {'issues': issues, 'scientificApproval': False, 'authoredValuesPreserved': True}
    result = previous.field_feedback(lowered, aliases)
    for issue in result['issues']:
        parts = issue['path'].split('/')
        if len(parts) >= 5 and parts[1] == 'steps' and parts[3] == 'reads':
            read = value['steps'][int(parts[2])]['reads'][int(parts[4])]
            if len(parts) == 6 and parts[5] == 'outputId' and 'savedOutputId' in read:
                parts[5] = 'savedOutputId'; issue['path'] = '/'.join(parts)
            try:
                actual = value
                for part in issue['path'].split('/')[1:]: actual = actual[int(part)] if isinstance(actual, list) else actual[part]
                issue.pop('actual', None); issue.pop('actualInInvalidMetadata', None)
                if len(json.dumps(actual, ensure_ascii=False).encode()) <= 256: issue['actual'] = deepcopy(actual)
                else: issue['actualInInvalidMetadata'] = issue['path']
                issue['actualPresent'] = True
            except (KeyError, TypeError, IndexError, ValueError): issue['actualPresent'] = False
        if issue['code'] == 'metadata.read.unknown_state':
            issue['expected'] = 'declared persistent state; calculated results use stepIndex/outputId/selector or stepIndex/savedOutputId/selector'
            for match in issue.get('outputMatches', []):
                stage = match.pop('outputStage')
                if stage == 'record': match['savedOutputId'] = match.pop('outputId')
    return result


def descriptor():
    result = previous.descriptor(); result['name'] = 'metadata_result_refs_v1'
    changed = 0
    for definition in result['schema']['$defs'].values():
        if not isinstance(definition, dict) or not isinstance(definition.get('anyOf'), list): continue
        branches = []
        for branch in definition['anyOf']:
            props = branch.get('properties', {}) if isinstance(branch, dict) else {}
            if set(props) == {'stepIndex', 'outputStage', 'outputId', 'selector'}:
                direct = deepcopy(branch); direct['properties'].pop('outputStage'); direct['required'].remove('outputStage')
                saved = deepcopy(direct); saved['properties']['savedOutputId'] = saved['properties'].pop('outputId')
                saved['required'] = ['savedOutputId' if k == 'outputId' else k for k in saved['required']]
                branches.extend((direct, saved)); changed += 1
            else: branches.append(branch)
        definition['anyOf'] = branches
    if changed != 1: raise ValueError('Result-reference schema shape changed')
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
