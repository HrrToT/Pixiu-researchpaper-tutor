"""Proposed state layouts/initializers. No allocation, execution or science approval."""
import json
import math

from services.deep_research.group_spec import validate_operation

STATE_CONTRACT = '''stateDefinitions is a nonempty list of {name:unique,dtype:nonblank,
shape:[positive integers OR {inputIndex:existing input index,axis:nonnegative integer}],
initializer:one of {mode:constant,value:finite scalar or rectangular literal array},
{mode:uniform,low:number,high:number,rng:implementation,seed:{mode:data_seed} OR {mode:fixed,value:integer}},
{mode:normal,mean:number,std:positive number,rng:implementation,seed:seed object},
{mode:operation,inputIndices:[existing input indices],rule:{action,parameters}}}.
Constant values broadcast over the declared shape; scalar shape is []. Uniform needs
low<high. data_seed uses each current data seed; fixed uses a chosen nonnegative seed.
Reset the named RNG per state/seed and record its implementation version at execution.
Operation inputs are explicit; [] permits an input-free analytic rule, not copying an
undeclared state. Rule parameters define actual transformations/values. List EVERY
required state, not just its count/shape; scientific compatibility is checked separately.'''


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _index(value, count):
    return type(value) is int and 0 <= value < count


def _literal_shape(value, dtype, depth=0):
    if depth > 16:
        return None
    if isinstance(value, list):
        if not value:
            return None
        shapes = [_literal_shape(item, dtype, depth + 1) for item in value]
        if shapes[0] is None or any(shape != shapes[0] for shape in shapes):
            return None
        return [len(value), *shapes[0]]
    if (_number(value) or (type(value) is bool and dtype == 'bool')
            or (isinstance(value, str) and dtype in {'str', 'string'})):
        return []
    return None


def state_definition_errors(states, inputs):
    if not isinstance(states, list) or not 1 <= len(states) <= 128:
        return ['states.required']
    input_count = len(inputs) if isinstance(inputs, list) else 0
    errors, names = [], set()
    for state in states:
        if (not isinstance(state, dict) or set(state) != {'name', 'dtype', 'shape', 'initializer'}
                or not isinstance(state.get('name'), str) or not state['name'].strip()
                or state['name'] in names or not isinstance(state.get('dtype'), str) or not state['dtype'].strip()):
            errors.append('states.definition')
            continue
        names.add(state['name'])
        shape = state['shape']
        shape_valid = isinstance(shape, list) and len(shape) <= 16
        if shape_valid:
            for dimension in shape:
                if type(dimension) is int and dimension > 0:
                    continue
                if (isinstance(dimension, dict) and set(dimension) == {'inputIndex', 'axis'}
                        and _index(dimension['inputIndex'], input_count)
                        and type(dimension['axis']) is int and dimension['axis'] >= 0):
                    continue
                shape_valid = False
                break
        if not shape_valid:
            errors.append('states.shape')
        initializer = state['initializer']
        if not isinstance(initializer, dict):
            errors.append('states.initializer')
            continue
        mode = initializer.get('mode')
        if mode == 'constant':
            literal = _literal_shape(initializer.get('value'), state['dtype'])
            if set(initializer) != {'mode', 'value'} or literal is None:
                errors.append('states.constant')
            elif shape_valid and (len(literal) > len(shape) or any(
                    n != 1 and type(d) is int and n != d
                    for n, d in zip(reversed(literal), reversed(shape)))):
                errors.append('states.constant_shape')
        elif mode in ('uniform', 'normal'):
            fields = {'mode', 'seed', 'rng', *({'low', 'high'} if mode == 'uniform' else {'mean', 'std'})}
            if set(initializer) != fields:
                errors.append('states.distribution')
            if not isinstance(initializer.get('rng'), str) or not initializer['rng'].strip():
                errors.append('states.rng')
            first, second = (initializer.get('low'), initializer.get('high')) if mode == 'uniform' else (
                initializer.get('mean'), initializer.get('std'))
            if not _number(first) or not _number(second) or (first >= second if mode == 'uniform' else second <= 0):
                errors.append('states.distribution_parameters')
            seed = initializer.get('seed')
            if not isinstance(seed, dict) or not (
                    seed == {'mode': 'data_seed'}
                    or (set(seed) == {'mode', 'value'} and seed.get('mode') == 'fixed'
                        and type(seed.get('value')) is int and seed['value'] >= 0)):
                errors.append('states.seed')
        elif mode == 'operation':
            indices = initializer.get('inputIndices')
            if (set(initializer) != {'mode', 'inputIndices', 'rule'} or not isinstance(indices, list)
                    or any(not _index(index, input_count) for index in indices)
                    or len(indices) != len(set(indices))):
                errors.append('states.operation_inputs')
            rule = initializer.get('rule')
            try:
                rule_errors = validate_operation(rule, 'states.rule')
            except (TypeError, ValueError):
                rule_errors = ['states.rule']
            if rule_errors or (isinstance(rule, dict) and rule.get('parameters') == []):
                errors.append('states.operation_rule')
        else:
            errors.append('states.initializer_mode')
    return list(dict.fromkeys(errors))


def state_definitions_text(states):
    """Render exact proposed values without implying the experiment was executed."""
    from services.deep_research.operation_text import operation_text
    lines = []
    for state in states:
        dims = [str(d) if type(d) is int else f"输入{d['inputIndex']}的第{d['axis']}轴"
                for d in state['shape']]
        shape = '×'.join(dims) if dims else '标量'
        init = state['initializer']
        if init['mode'] == 'constant':
            meaning = '常量 ' + json.dumps(init['value'], ensure_ascii=False, allow_nan=False)
        elif init['mode'] in ('normal', 'uniform'):
            meaning = (f"均匀分布 [{init['low']}, {init['high']})" if init['mode'] == 'uniform'
                       else f"正态分布，均值{init['mean']}，标准差{init['std']}")
            meaning += '；使用当前数据种子' if init['seed']['mode'] == 'data_seed' else f"；固定种子{init['seed']['value']}"
            meaning += '；逐状态重置 ' + init['rng'] + '，执行时记录实现版本'
        else:
            meaning = operation_text(init['rule']) + ('；输入索引 ' + '、'.join(map(str, init['inputIndices']))
                if init['inputIndices'] else '；无外部输入')
        lines.append(f"- {state['name']}：{state['dtype']}，形状{shape}；初值为{meaning}")
    return '\n'.join(lines)
