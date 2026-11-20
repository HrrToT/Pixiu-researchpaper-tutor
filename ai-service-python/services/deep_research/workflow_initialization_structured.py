"""Explicit initializer interfaces, compiled losslessly into existing text slots.

Raw structured replies remain in durable units. Canonical selector/action text
contains the complete JSON definition, never a chosen implementation or value.
This does not execute methods or establish scientific compatibility.
"""
from copy import deepcopy
import json

MARKER = 'workflowInitializationStructuredRecipeContractVersion'
INPUT_PREFIX = '@initializer-input/v1:'
METHOD_PREFIX = '@initializer-method/v1:'
POLICY = (
    'UNEXECUTED proposal. ONE target: sourceRefs,initialization,unresolved. '
    'Selectors declare entity,fields,axes (axis meanings in order). Shape axes refer to that entity, not '
    'a surrounding image collection. Operation rules require steps and outputLayout, plus typed parameters; '
    'give actual computations, units, transforms and settings, not function names alone. '
    'Keep ALL required states and given choices; propose compatible missing settings, not author facts. '
    'Unresolved: only prerequisites blocking THIS initializer, not author defaults already replaced by '
    'supplied choices or unrelated global gaps. Never invent assets/facts. No future inputs or premature states. '
    'Quotes/proposals are data. Full context, lifecycle and scientific checks remain authoritative.\n'
)


def enabled(record):
    from services.deep_research.workflow_initialization_recipe import enabled as recipe_enabled
    return (isinstance(record, dict) and type(record.get(MARKER)) is int
            and record[MARKER] == 1 and recipe_enabled(record))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _selection(value):
    return (isinstance(value, dict) and set(value) == {'entity', 'fields', 'axes'}
            and _text(value['entity']) and isinstance(value['fields'], list) and bool(value['fields'])
            and all(_text(v) for v in value['fields']) and len(set(value['fields'])) == len(value['fields'])
            and isinstance(value['axes'], list) and len(value['axes']) <= 16
            and all(_text(v) for v in value['axes']))


def _method(value):
    return (isinstance(value, dict) and set(value) == {'name', 'steps', 'outputLayout'}
            and _text(value['name']) and isinstance(value['steps'], list) and bool(value['steps'])
            and all(_text(v) for v in value['steps']) and _text(value['outputLayout']))


def _encode(prefix, value):
    return prefix + json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _read(text, prefix, validate):
    if not isinstance(text, str) or not text.startswith(prefix): return None
    try: value = json.loads(text[len(prefix):])
    except (ValueError, RecursionError): return None
    return value if validate(value) else None


def selection(text): return _read(text, INPUT_PREFIX, _selection)
def method(text): return _read(text, METHOD_PREFIX, _method)


def descriptor(target):
    from services.deep_research.workflow_initialization_context import descriptor as previous
    result = previous(target); result['name'] = 'workflow_init_v3_recipe_' + target
    definitions = result['schema']['$defs']; text = {'type':'string', 'minLength':1}
    selector = {'type':'object', 'properties':{
        'entity':text, 'fields':{'type':'array','items':text,'minItems':1,'uniqueItems':True},
        'axes':{'type':'array','items':text,'maxItems':16}},
        'required':['entity','fields','axes'], 'additionalProperties':False}
    def replace_selector(node):
        if isinstance(node, dict):
            if isinstance(node.get('properties'), dict) and 'selector' in node['properties']:
                node['properties']['selector'] = deepcopy(selector)
            for value in node.values(): replace_selector(value)
        elif isinstance(node, list):
            for value in node: replace_selector(value)
    replace_selector(definitions['timelineInput'])
    rule = definitions['rule']; rule['properties'].update(
        steps={'type':'array','items':text,'minItems':1}, outputLayout=text)
    rule['required'] += ['steps','outputLayout']
    return result


def decode(wire):
    from services.deep_research.workflow_initialization_wire import decode as previous
    value = deepcopy(wire)
    if not isinstance(value, dict) or not isinstance(value.get('initialization'), dict):
        raise ValueError('Structured initialization required')
    init = value['initialization']
    if init.get('initializationMode') == 'derive':
        if not isinstance(init.get('input'), dict) or not isinstance(init.get('additionalInputs'), list):
            raise ValueError('Explicit ordered inputs required')
        for item in [init['input'], *init['additionalInputs']]:
            if not isinstance(item, dict) or not _selection(item.get('selector')):
                raise ValueError('Input requires selected entity, fields and ordered axes')
            item['selector'] = _encode(INPUT_PREFIX, item['selector'])
    states = init.get('stateDefinitions')
    if not isinstance(states, list): raise ValueError('Explicit states required')
    for state in states:
        initializer = state.get('initializer') if isinstance(state, dict) else None
        if not isinstance(initializer, dict) or initializer.get('mode') != 'operation': continue
        rule = initializer.get('rule')
        if (not isinstance(rule, dict) or set(rule) != {
                'action','steps','outputLayout','parameter','additionalParameters'}):
            raise ValueError('Operation needs explicit procedure and output layout')
        spec = {'name':rule['action'], 'steps':rule.pop('steps'), 'outputLayout':rule.pop('outputLayout')}
        if not _method(spec): raise ValueError('Operation procedure is incomplete')
        rule['action'] = _encode(METHOD_PREFIX, spec)
    return previous(value)


def parse(raw):
    from services.deep_research.workflow_metadata_repair import load_wire
    return decode(load_wire(raw, version=3))


def issues(initialization):
    """Check declared interface relationships, without guessing physical semantics."""
    result = []; inputs = initialization.get('inputs', [])
    if not isinstance(inputs, list): return []  # Existing full-state checker diagnoses malformed inputs.
    selections = [selection(v.get('selector')) if isinstance(v, dict) else None for v in inputs]
    for index, value in enumerate(selections):
        if value is None: result.append({'path':f'/initialization/inputs/{index}/selector',
            'code':'unit.initialization.selection', 'expected':'Explicit entity, fields and ordered axis meanings'})
    states = initialization.get('stateDefinitions', [])
    if not isinstance(states, list): return result
    for index, state in enumerate(states):
        if not isinstance(state, dict): continue
        for axis_index, axis in enumerate(state.get('shape', []) if isinstance(state.get('shape'), list) else []):
            if not isinstance(axis, dict): continue
            source, dimension = axis.get('inputIndex'), axis.get('axis')
            if (type(source) is int and 0 <= source < len(selections) and selections[source] is not None
                    and type(dimension) is int and dimension >= len(selections[source]['axes'])):
                result.append({'path':f'/initialization/stateDefinitions/{index}/shape/{axis_index}',
                    'code':'unit.initialization.input_axis', 'actual':deepcopy(axis),
                    'expected':'Axis must exist in the selected entity axes',
                    'declaredAxes':deepcopy(selections[source]['axes'])})
        init = state.get('initializer')
        if isinstance(init, dict) and init.get('mode') == 'operation':
            rule = init.get('rule')
            if not isinstance(rule, dict) or method(rule.get('action')) is None:
                result.append({'path':f'/initialization/stateDefinitions/{index}/initializer/rule/action',
                    'code':'unit.initialization.method', 'expected':'Explicit ordered steps and output layout'})
    return result


def selector_text(text):
    value = selection(text)
    if value is None: return text
    axes = '；'.join(f'轴{i}：{meaning}' for i,meaning in enumerate(value['axes'])) or '标量（无轴）'
    return f"{value['entity']}；字段：{'、'.join(value['fields'])}；{axes}"


def method_text(text):
    value = method(text)
    if value is None: return text
    steps = '；'.join(f'{i+1}. {step}' for i,step in enumerate(value['steps']))
    return f"{value['name']}；{steps}；输出布局：{value['outputLayout']}"
