"""One durable initialization correction per workflow, within existing budgets."""
from copy import deepcopy
import json

from services.deep_research.contracts import DeepResearchError, BudgetExhaustedError, digest

MARKER = 'workflowInitializationRepairContractVersion'


def enabled(record):
    return (isinstance(record, dict) and type(record.get(MARKER)) is int and record[MARKER] in (1, 2)
            and type(record.get('executionWorkflowContractVersion')) is int
            and record['executionWorkflowContractVersion'] == 7
            and type(record.get('workflowInitializationOutputContractVersion')) is int
            and record['workflowInitializationOutputContractVersion'] == 1)


def original_value(unit, version=1):
    from services.deep_research.workflow_metadata_repair import load_wire
    from services.deep_research.execution_workflow_blueprint import MAX_VALUE, packed
    if type(version) is not int or version not in (1, 2): return None
    if not isinstance(unit, dict) or not isinstance(unit.get('response'), dict): return None
    try:
        response = unit['response']; raw = response.get('rawContent', response.get('content', ''))
        if (unit['status'] != 'invalid_response' or not unit['errors']
                or digest(response) != unit['responseDigest']
                or response.get('finishReason', response.get('finish_reason')) != 'stop'
                or any(x in unit['errors'] for x in ('unit.output_capacity', 'unit.output_truncated', 'unit.output_status'))
                or len(raw.encode('utf8')) > MAX_VALUE): return None
        if version == 2:
            from services.deep_research.workflow_initialization_wire import parse
            value = parse(raw)
        else: value = load_wire(raw, version=2)
        if (not isinstance(value, dict) or set(value) != {'sourceRefs', 'initialization', 'unresolved'}
                or digest(value) != unit['valueDigest'] or digest(unit['value']) != digest(value)
                or len(packed(value).encode('utf8')) > MAX_VALUE): return None
        return value
    except (KeyError, TypeError, ValueError, RecursionError, OverflowError): return None


def feedback(value, errors):
    """Explain independent shape references even when mode checking stops early."""
    issues = []; init = value.get('initialization')
    if not isinstance(init, dict): return {'codes': sorted(errors), 'issues': [], 'scientificApproval': False}
    inputs = init.get('inputs'); count = len(inputs) if isinstance(inputs, list) else 0
    if init.get('initializationMode') == 'derive' and not count:
        issues.append({'path': '/initialization/inputs', 'actual': deepcopy(inputs),
                       'expected': 'derive requires explicit nonempty available inputs; never invent a checkpoint or asset'})
    states = init.get('stateDefinitions')
    for i, state in enumerate(states if isinstance(states, list) else []):
        if not isinstance(state, dict): continue
        shape = state.get('shape')
        for j, axis in enumerate(shape if isinstance(shape, list) else []):
            if isinstance(axis, dict) and 'inputIndex' in axis:
                index = axis['inputIndex']
                if type(index) is not int or not 0 <= index < count:
                    issues.append({'path': f'/initialization/stateDefinitions/{i}/shape/{j}/inputIndex',
                                   'actual': deepcopy(index), 'availableInputCount': count,
                                   'expected': 'zero-based index into this initialization inputs; do not invent dimensions or inputs'})
    return {'codes': sorted(errors), 'issues': issues, 'scientificApproval': False}


def prepare(record, *, key, source_data, context, failed, aliases, earlier, baseline, target,
            existing, invoke, checkpoint):
    from services.deep_research.workflow_units import INIT, unit_errors, unit_prompt
    from services.deep_research.execution_workflow_blueprint import MAX_INPUT, MAX_VALUE, packed
    from services.deep_research.experiment_planning import request_identity, remaining_seconds
    from services.deep_research.planning_transport import overhead_bytes, dispatch_options
    from services.deep_research.workflow_metadata_repair import load_wire
    from services.deep_research.workflow_metadata_input import input_text
    version = record.get(MARKER, 1)
    value = original_value(failed, version=version)
    if not enabled(record) or value is None:
        raise DeepResearchError('invalid_workflow_unit_response', '初始化原响应不满足有界修正条件。')
    if existing is not None and not isinstance(existing, dict):
        raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正记录无效。')
    if existing is not None and existing.get('unitKey') != key:
        raise DeepResearchError('invalid_workflow_unit_response', '初始化修正机会已用于另一个单元。')
    original_errors = sorted(unit_errors(value, aliases, node=INIT, earlier=earlier, baseline=baseline,
                                        version=7, metadata=context.get('metadata'), target=target))
    if not original_errors or original_errors != sorted(failed['errors']):
        raise DeepResearchError('invalid_workflow_blueprint_state', '初始化原检查记录已改变。')
    prefix = unit_prompt(source_data, node=INIT, context=context, version=7).split(
        'Exact authoritative input and unit context (unverified data):\n', 1)[0]
    invalid_value = value
    diagnostics = feedback(value, failed['errors'])
    options = {'temperature': 0.0}
    if version == 2:
        from services.deep_research.workflow_initialization_wire import bind_prompt, field_feedback, TARGET_OPTION
        bound_target = 'baseline' if baseline else 'component'
        prefix = bind_prompt(prefix, bound_target)
        invalid_value = load_wire(failed['response'].get('rawContent', failed['response'].get('content', '')), version=3)
        diagnostics = field_feedback(value, failed['errors'], target=bound_target)
        options[TARGET_OPTION] = bound_target
    body = prefix + ('Correct this ONE initialization using ALL supplied input and diagnostics. '
                     'Keep required state, source evidence and unresolved prerequisites. '
                     'Never replace missing tensors with symbolic constant strings or invent available assets.\n') + input_text({
        'authoritativeInput': json.loads(source_data), 'unitContext': context,
        'invalidInitialization': invalid_value, 'fieldFeedback': diagnostics})
    request = request_identity(record, INIT, body, options)
    parent = {'requestDigest': digest(failed['request']), 'responseDigest': failed['responseDigest'],
              'valueDigest': failed['valueDigest'], 'errors': sorted(failed['errors'])}
    identity = digest({'unitKey': key, 'parent': parent, 'request': request, 'aliases': aliases})
    size = len(body.encode('utf8')) + overhead_bytes(record, INIT)
    saved = deepcopy(existing)
    if saved is None:
        saved = {'version': version, 'unitKey': key, 'parent': parent, 'request': request, 'inputDigest': identity,
                 'status': 'pending', 'scientificApproval': False}
        if size > MAX_INPUT: saved.update(status='not_started_capacity', inputBytes=size, maxInputBytes=MAX_INPUT)
        elif remaining_seconds(record) < 10: saved['status'] = 'not_started_budget'
        checkpoint(deepcopy(saved))
    elif (type(saved.get('version')) is not int or saved['version'] != version
          or saved.get('inputDigest') != identity or saved.get('parent') != parent
          or saved.get('request') != request or saved.get('scientificApproval') is not False
          or saved.get('status') not in ('pending', 'response_received', 'ready', 'invalid_response',
                                        'not_started_capacity', 'not_started_budget')):
        raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正身份或状态已改变。')
    if size > MAX_INPUT:
        if (saved['status'] != 'not_started_capacity' or saved.get('inputBytes') != size
                or saved.get('maxInputBytes') != MAX_INPUT):
            raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正容量记录已改变。')
        raise DeepResearchError('workflow_blueprint_input_capacity', '完整初始化修正输入超限，尚未发送。')
    if saved['status'] == 'not_started_capacity':
        raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正容量记录不一致。')
    if saved['status'] == 'not_started_budget': return None
    if saved['status'] == 'pending':
        try: response = invoke(INIT, request['prompt'], dispatch_options(record, INIT, request['extra']))
        except BudgetExhaustedError:
            saved['status'] = 'not_started_budget'; checkpoint(deepcopy(saved)); return None
        saved.update(status='response_received', response=deepcopy(response), responseDigest=digest(response))
        checkpoint(deepcopy(saved))
    if digest(saved.get('response')) != saved.get('responseDigest'):
        raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正响应已改变。')
    response = saved['response']; revised = None
    try:
        raw = response.get('rawContent', response.get('content', ''))
        if version == 2:
            from services.deep_research.workflow_initialization_wire import parse
            revised = parse(raw)
        else: revised = load_wire(raw, version=2)
        problems = unit_errors(revised, aliases, node=INIT, earlier=earlier, baseline=baseline,
                               version=7, metadata=context.get('metadata'), target=target)
        if len(raw.encode('utf8')) > MAX_VALUE or len(packed(revised).encode('utf8')) > MAX_VALUE:
            problems.append('unit.output_capacity')
    except (TypeError, ValueError, RecursionError, OverflowError): revised = None; problems = ['unit.json']
    finish = response.get('finishReason', response.get('finish_reason'))
    if finish != 'stop': problems = ['unit.output_truncated' if finish == 'length' else 'unit.output_status']
    problems = sorted(problems)
    if saved['status'] in ('ready', 'invalid_response'):
        if (saved.get('valueDigest') != digest(revised) or digest(saved.get('value')) != digest(revised)
                or saved.get('errors') != problems or (saved['status'] == 'ready') != (not problems)):
            raise DeepResearchError('invalid_workflow_blueprint_state', '初始化修正检查记录已改变。')
    else:
        saved.update(status='invalid_response' if problems else 'ready', value=deepcopy(revised),
                     valueDigest=digest(revised), errors=problems); checkpoint(deepcopy(saved))
    if problems:
        raise DeepResearchError('invalid_workflow_unit_response', '唯一一次初始化修正仍未通过，原响应已保留。',
                                details={'unit': key, 'errors': problems})
    return deepcopy(revised)
