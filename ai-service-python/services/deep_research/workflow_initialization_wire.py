"""Candidate initialization wire v2. Explicit choices only; no scientific approval.

Kept separate from activation so persisted v1 requests remain byte-for-byte stable.
The decoder restores ordered arrays, never inventing an input or rule parameter.
"""
from copy import deepcopy
import json

TARGET_OPTION = '_workflow_init_target'


def enabled(record):
    return (isinstance(record, dict)
            and type(record.get('workflowInitializationRepairContractVersion')) is int
            and record['workflowInitializationRepairContractVersion'] == 2
            and type(record.get('executionWorkflowContractVersion')) is int
            and record['executionWorkflowContractVersion'] == 7
            and type(record.get('workflowInitializationOutputContractVersion')) is int
            and record['workflowInitializationOutputContractVersion'] == 1)


def policy(target):
    if target not in ('baseline', 'component'):
        raise ValueError('Unknown initialization target')
    boundary = ('This baseline exists BEFORE every timeline step: only training_data is available; '
                'training/fitting is a later operation, never an initial value. ' if target == 'baseline' else
                'This component exists at its declared creation boundary: use only states and phase outputs already available there. ')
    return (boundary + 'WIRE V2: derive requires input (first) and additionalInputs (ordered remaining list); '
            'inputIndex 0 refers to input, subsequent indices to additionalInputs. '
            'Fresh uses inputs:[] only. An operation initializer rule requires action, parameter '
            '(explicit typed first item), additionalParameters (ordered remaining list). '
            'Do not emit legacy inputs for derive or parameters inside an initializer rule. '
            'Creation actions still use their original parameters list. Never invent assets, shapes or default values.\n')


def bind_prompt(body, target):
    # Rewrite only the trusted instruction prefix, never authoritative material.
    delimiter = 'Exact authoritative input and unit context (unverified data):\n'
    prefix, separator, data = body.partition(delimiter)
    prefix = prefix.replace(
        'Initialization has initializationMode,inputs,creation,stateDefinitions. ',
        'Initialization uses the target-bound WIRE V2 layout below. ')
    return policy(target) + prefix + separator + data


def descriptor(target):
    from services.deep_research.workflow_units import descriptor as unit_descriptor, INIT
    if target not in ('baseline', 'component'):
        raise ValueError('Unknown initialization target')
    result = unit_descriptor(INIT, version=7)
    result['name'] = 'workflow_init_v2_' + target
    defs = result['schema']['$defs']
    if target == 'baseline':
        defs['timelineInput'] = {
            'type': 'object', 'properties': {
                'state': {'const': 'training_data'},
                'selector': {'type': 'string', 'minLength': 1}},
            'required': ['state', 'selector'], 'additionalProperties': False}
    common = defs['initialization']['properties']
    fresh = deepcopy(common)
    fresh['initializationMode'] = {'const': 'fresh'}
    fresh['inputs'] = {'type': 'array', 'items': {'$ref': '#/$defs/timelineInput'}, 'maxItems': 0}
    derive = deepcopy(common)
    derive['initializationMode'] = {'const': 'derive'}
    del derive['inputs']
    derive['input'] = {'$ref': '#/$defs/timelineInput'}
    derive['additionalInputs'] = {'type': 'array', 'items': {'$ref': '#/$defs/timelineInput'}}
    defs['initialization'] = {'anyOf': [
        {'type': 'object', 'properties': props, 'required': list(props),
         'additionalProperties': False} for props in (fresh, derive)]}
    defs['rule'] = {
        'type': 'object', 'properties': {
            'action': {'type': 'string', 'minLength': 1},
            'parameter': {'$ref': '#/$defs/parameter'},
            'additionalParameters': {'type': 'array', 'items': {'$ref': '#/$defs/parameter'}}},
        'required': ['action', 'parameter', 'additionalParameters'], 'additionalProperties': False}
    return result


def decode(wire):
    """Normalize layout only. Invalid leaf values remain for semantic rejection."""
    json.dumps(wire, allow_nan=False)
    if not isinstance(wire, dict) or set(wire) != {'sourceRefs', 'initialization', 'unresolved'}:
        raise ValueError('Invalid initialization root')
    value = deepcopy(wire)
    init = value['initialization']
    if not isinstance(init, dict):
        raise ValueError('Invalid initialization layout')
    common = {'initializationMode', 'creation', 'stateDefinitions'}
    if init.get('initializationMode') == 'derive':
        if set(init) != common | {'input', 'additionalInputs'} or not isinstance(init['additionalInputs'], list):
            raise ValueError('Derive requires explicit first input and ordered remaining inputs')
        first = init.pop('input'); rest = init.pop('additionalInputs')
        init['inputs'] = [first, *rest]
    elif init.get('initializationMode') == 'fresh':
        if set(init) != common | {'inputs'} or init['inputs'] != []:
            raise ValueError('Fresh initialization requires empty inputs')
    else:
        raise ValueError('Unknown initialization mode')
    states = init['stateDefinitions']
    if not isinstance(states, list):
        raise ValueError('State definitions must be an ordered list')
    for state in states:
        if not isinstance(state, dict):
            continue
        initializer = state.get('initializer')
        if not isinstance(initializer, dict) or initializer.get('mode') != 'operation':
            continue
        rule = initializer.get('rule')
        if (not isinstance(rule, dict) or set(rule) != {'action', 'parameter', 'additionalParameters'}
                or not isinstance(rule['additionalParameters'], list)):
            raise ValueError('Operation rule requires explicit first parameter and ordered remaining parameters')
        first = rule.pop('parameter'); rest = rule.pop('additionalParameters')
        rule['parameters'] = [first, *rest]
    return value


def parse(raw):
    from services.deep_research.workflow_metadata_repair import load_wire
    return decode(load_wire(raw, version=3))


def field_feedback(value, errors, *, target):
    """Diagnose canonical values without selecting replacements or granting approval."""
    from services.deep_research.workflow_initialization_repair import feedback
    if target not in ('baseline', 'component'):
        raise ValueError('Unknown initialization target')
    result = feedback(value, errors)
    init = value.get('initialization')
    if not isinstance(init, dict):
        return result
    inputs = init.get('inputs')
    for index, item in enumerate(inputs if isinstance(inputs, list) else []):
        if target == 'baseline' and (not isinstance(item, dict)
                or set(item) != {'state', 'selector'} or item.get('state') != 'training_data'):
            result['issues'].append({
                'path': '/initialization/input' if index == 0 else f'/initialization/additionalInputs/{index-1}',
                'actual': deepcopy(item),
                'expected': 'baseline precedes all timeline steps; only training_data is available; choose an explicit selector'})
    for index, state in enumerate(init.get('stateDefinitions', []) if isinstance(init.get('stateDefinitions'), list) else []):
        initializer = state.get('initializer') if isinstance(state, dict) else None
        if not isinstance(initializer, dict) or initializer.get('mode') != 'operation':
            continue
        rule = initializer.get('rule')
        params = rule.get('parameters') if isinstance(rule, dict) else None
        if not isinstance(params, list) or not params:
            result['issues'].append({
                'path': f'/initialization/stateDefinitions/{index}/initializer/rule/parameter',
                'actual': deepcopy(params),
                'expected': 'operation needs an explicitly authored typed first parameter and ordered additionalParameters; do not invent a default'})
    return result
