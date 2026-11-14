"""Strict outer framing and read-only operation diagnostics for revision 3."""
from copy import deepcopy
import json
import re

from services.deep_research.group_spec import validate_operation
from services.deep_research.workflow_metadata_wire_feedback import feedback


def json_body(raw):
    """Unwrap exactly one complete outer fence; never extract embedded JSON."""
    if not isinstance(raw, str): raise TypeError('Metadata response must be text')
    text = raw.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\r?\n(.*?)\r?\n```', text, flags=re.DOTALL)
        if match is None: raise ValueError('Incomplete or ambiguous metadata fence')
        text = match.group(1)
    return text


def operation_feedback(wire):
    """Retain all wire issues and point at operation errors without choosing values."""
    result = feedback(wire)
    for i, phase in enumerate(wire['phaseRows']):
        op = phase[9]; path = f'/phaseRows/{i}/9'
        if not isinstance(op, list) or len(op) != 2 or not isinstance(op[1], list):
            result['issues'].append({'code': 'wire.operation.columns', 'path': path,
                'expected': '[action,[[unique_name,number|choice,value],...]]', 'actual': deepcopy(op)})
            continue
        parameters = []; seen = set()
        for j, param in enumerate(op[1]):
            if not isinstance(param, list) or len(param) != 3:
                result['issues'].append({'code': 'wire.parameter.columns', 'path': f'{path}/1/{j}',
                    'expected': '[name,number|choice,value]', 'actual': deepcopy(param)})
                continue
            parameters.append(dict(zip(('name', 'type', 'value'), param)))
            if isinstance(param[0], str):
                if param[0] in seen:
                    result['issues'].append({'code': 'wire.parameter.duplicate_name',
                        'path': f'{path}/1/{j}/0', 'expected': 'unique parameter name within this operation',
                        'actual': param[0]})
                seen.add(param[0])
        errors = validate_operation({'action': op[0], 'parameters': parameters})
        if errors:
            result['issues'].append({'code': 'wire.operation.invalid', 'path': path,
                'expected': 'valid operation with uniquely named typed parameters',
                'actual': deepcopy(op), 'errors': sorted(errors)})
    result['issues'].sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return result
