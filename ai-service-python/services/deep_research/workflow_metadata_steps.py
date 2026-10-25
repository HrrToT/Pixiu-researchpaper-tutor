"""Typed step IR assessment. No runtime activation or historical conversion.

Array positions supply identity. An authored observation explicitly measures
and saves values; lowering adds only wiring/IDs, never scientific operations.
Primitive evaluate/record steps remain available for non-atomic schedules.
"""
from copy import deepcopy

from services.deep_research.workflow_metadata_rows import COMMON, _json_copy
from services.deep_research import workflow_metadata_ordered as ordered

NAME = 'typed_workflow_steps_v1'
OP_FIELDS = {'scope', 'kind', 'groups', 'sharing', 'reads', 'updates', 'outputs', 'action', 'budget'}
OBS_FIELDS = {'scope', 'kind', 'groups', 'reads', 'measurement', 'outputs', 'recording'}


def complete_scaffolding(value):
    try: value = _json_copy(value)
    except (TypeError, ValueError, RecursionError, OverflowError): return False
    if (not isinstance(value, dict) or set(value) != {*COMMON, 'components', 'steps'}
            or not isinstance(value['steps'], list) or not 1 <= len(value['steps']) <= 128
            or not isinstance(value['components'], list) or len(value['components']) > 8): return False
    for c in value['components']:
        if (not isinstance(c, dict) or set(c) != {'componentId', 'appliesTo', 'lifecycle'}
                or not isinstance(c['lifecycle'], dict)
                or set(c['lifecycle']) != {'scope', 'createBefore', 'disposeAfter'}): return False
    for step in value['steps']:
        if not isinstance(step, dict) or set(step) not in (OP_FIELDS, OBS_FIELDS): return False
        if set(step) == OBS_FIELDS and (not isinstance(step['recording'], dict)
                or set(step['recording']) != {'inputs', 'action', 'outputs'}): return False
    return True


def _text(v): return isinstance(v, str) and bool(v.strip())


def _strings(v):
    return isinstance(v, list) and bool(v) and all(_text(x) for x in v) and len(v) == len(set(v))


def _stages(step): return ('measurement', 'record') if step['kind'] == 'observe' else ('operation',)


def issues(value):
    if not complete_scaffolding(value): raise ValueError('Incomplete typed steps')
    result = []; steps = value['steps']; count = len(steps)
    def add(code, path, actual, expected):
        result.append({'code': code, 'path': path, 'actual': deepcopy(actual), 'expected': expected})
    def index(v, path, *, nullable=False):
        if nullable and v is None: return
        if type(v) is not int or not 0 <= v < count:
            add('steps.index', path, v, 'explicit zero-based step index within the authored array; never guess/coerce')
    expanded = 0
    for i, step in enumerate(steps):
        kind = step['kind']; path = f'/steps/{i}'
        expected = OBS_FIELDS if kind == 'observe' else OP_FIELDS
        if kind not in ('setup', 'fit', 'evaluate', 'record', 'observe') or set(step) != expected:
            add('steps.kind', path, step, 'complete primitive operation or explicit observe measurement/recording'); continue
        expanded += len(_stages(step))
        reads = step['reads']
        if not isinstance(reads, list): add('steps.reads', path+'/reads', reads, 'explicit input list'); continue
        for j, item in enumerate(reads):
            p = path+f'/reads/{j}'
            if isinstance(item, dict) and set(item) == {'state', 'selector'}: continue
            if not isinstance(item, dict) or set(item) != {'stepIndex', 'outputStage', 'outputId', 'selector'}:
                add('steps.read_fields', p, item, '{state,selector} or {stepIndex,outputStage,outputId,selector}'); continue
            ref = item['stepIndex']; index(ref, p+'/stepIndex')
            if type(ref) is int and 0 <= ref < count and item['outputStage'] not in _stages(steps[ref]):
                add('steps.output_stage', p+'/outputStage', item['outputStage'], 'operation for a primitive; measurement/record for observe')
        if kind == 'observe':
            if not isinstance(step['groups'], list) or len(step['groups']) != 1:
                add('steps.observation_group', path+'/groups', step['groups'], 'one explicitly chosen group; preserve other-arm observations')
            outputs = step['outputs']; recording = step['recording']; inputs = recording['inputs']
            if not _strings(outputs): add('steps.measurement_outputs', path+'/outputs', outputs, 'nonempty unique observation output IDs')
            if not _strings(recording['outputs']): add('steps.record_outputs', path+'/recording/outputs', recording['outputs'], 'nonempty unique saved-output IDs')
            if not isinstance(inputs, list) or not inputs:
                add('steps.record_inputs', path+'/recording/inputs', inputs, 'explicit nonempty local measurement selections'); continue
            valid = all(isinstance(x, dict) and set(x) == {'outputId', 'selector'}
                and _text(x['outputId']) and _text(x['selector']) for x in inputs)
            if not valid: add('steps.record_inputs', path+'/recording/inputs', inputs, '{outputId,selector} for each explicitly selected measurement')
            elif _strings(outputs) and {x['outputId'] for x in inputs} != set(outputs):
                add('steps.record_coverage', path+'/recording/inputs', inputs, 'persist all declared observation outputs; never synthesize missing selectors')
    if expanded > 128: add('steps.capacity', '/steps', expanded, 'at most 128 canonical phases; never truncate operations')
    for i, c in enumerate(value['components']):
        life = c['lifecycle']
        index(life['createBefore'], f'/components/{i}/lifecycle/createBefore')
        index(life['disposeAfter'], f'/components/{i}/lifecycle/disposeAfter', nullable=True)
    return result


def _identity(index, stage): return f'step_{index}_{stage}'


def view(value):
    if issues(value): raise ValueError('Unresolved authored step interface')
    value = _json_copy(value); steps = value.pop('steps'); phases = []; locations = []
    def read(item):
        if 'state' in item: return deepcopy(item)
        return {'phaseId': _identity(item['stepIndex'], item['outputStage']),
                'outputId': deepcopy(item['outputId']), 'selector': deepcopy(item['selector'])}
    for i, step in enumerate(steps):
        if step['kind'] != 'observe':
            phases.append({**deepcopy(step), 'phaseId': _identity(i, 'operation'), 'reads': [read(x) for x in step['reads']]})
            locations.append((i, 'operation')); continue
        common = {'scope': step['scope'], 'groups': deepcopy(step['groups']), 'sharing': 'per_group', 'updates': [], 'budget': None}
        phases.append({**deepcopy(common), 'kind': 'evaluate', 'phaseId': _identity(i, 'measurement'),
            'reads': [read(x) for x in step['reads']], 'outputs': deepcopy(step['outputs']), 'action': deepcopy(step['measurement'])})
        locations.append((i, 'measurement'))
        recording = step['recording']
        phases.append({**deepcopy(common), 'kind': 'record', 'phaseId': _identity(i, 'record'),
            'reads': [{'phaseId': _identity(i, 'measurement'), **deepcopy(x)} for x in recording['inputs']],
            'outputs': deepcopy(recording['outputs']), 'action': deepcopy(recording['action'])})
        locations.append((i, 'record'))
    for c in value['components']:
        life = c['lifecycle']; before = life['createBefore']; after = life['disposeAfter']
        life['createBefore'] = _identity(before, _stages(steps[before])[0])
        life['disposeAfter'] = _identity(after, _stages(steps[after])[-1]) if after is not None else None
    value['phases'] = phases
    return value, locations


def decode(value):
    return ordered.decode(view(value)[0], version=2)


def descriptor():
    schema = ordered.descriptor(2)
    schema['name'] = NAME; root = schema['schema']; defs = root['$defs']
    root['properties']['steps'] = root['properties'].pop('phases'); root['required'].remove('phases'); root['required'].append('steps')
    defs['stepInput'] = {'anyOf': [deepcopy(defs['timelineInput']['anyOf'][0]), {
        'type': 'object', 'properties': {'stepIndex': {'type': 'integer', 'minimum': 0, 'maximum': 127},
        'outputStage': {'enum': ['operation', 'measurement', 'record']}, 'outputId': {'type': 'string', 'minLength': 1},
        'selector': {'type': 'string', 'minLength': 1}},
        'required': ['stepIndex', 'outputStage', 'outputId', 'selector'], 'additionalProperties': False}]}
    branches = deepcopy(defs['phase']['anyOf'])
    for branch in branches:
        del branch['properties']['phaseId']; branch['required'].remove('phaseId')
        branch['properties']['reads']['items'] = {'$ref': '#/$defs/stepInput'}
    text = {'type': 'string', 'minLength': 1}
    def obj(props): return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
    saved = obj({'inputs': {'type': 'array', 'minItems': 1, 'items': obj({'outputId': text, 'selector': text})},
        'action': {'$ref': '#/$defs/operation'}, 'outputs': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': text}})
    props = branches[0]['properties']
    observe = obj({'scope': deepcopy(props['scope']), 'kind': {'const': 'observe'},
        'groups': deepcopy(branches[1]['properties']['groups']), 'reads': deepcopy(props['reads']),
        'measurement': {'$ref': '#/$defs/operation'}, 'outputs': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': text},
        'recording': saved})
    defs['step'] = {'anyOf': [observe, *branches]}
    root['properties']['steps']['items'] = {'$ref': '#/$defs/step'}
    del defs['phase']
    del defs['timelineInput']
    life = defs['lifecycle']['properties']
    life['createBefore'] = {'type': 'integer', 'minimum': 0, 'maximum': 127}
    life['disposeAfter'] = {'anyOf': [{'type': 'integer', 'minimum': 0, 'maximum': 127}, {'type': 'null'}]}
    return schema
