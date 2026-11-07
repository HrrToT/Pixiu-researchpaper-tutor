"""Version 6 metadata: named operation objects, with no inferred operations."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_rows as rows
from services.deep_research.group_spec import validate_operation
from services.deep_research.workflow_metadata_wire_feedback import feedback as wire_feedback

NAME = 'workflow_metadata_action_objects_v1'
POLICY = (
    'Each phase has ONE action OBJECT with exactly action (one nonblank operation name) and '
    'parameters (an array of {name,type,value} objects). Parameter types are number or choice. '
    'Do not use an action tuple, append another operation, or concatenate operation names. '
    'When several operations are needed, declare separate phases with explicit reads, outputs '
    'and dependencies; retain every operation, measurement and budget. A genuinely single '
    'combined measurement operation needs its full distinct parameters and all declared outputs. '
    'Never insert placeholder observed metric values into an unexecuted proposal.\n'
)


def encode(metadata):
    wire = rows.encode(metadata)
    for row, phase in zip(wire['phaseRows'], metadata['phases']):
        row[9] = deepcopy(phase['action'])
    return wire


def decode(wire):
    # Shape translation only. Never select, split, rename or drop operations.
    wire = deepcopy(wire)
    if not isinstance(wire, dict) or not isinstance(wire.get('phaseRows'), list):
        raise ValueError('Missing metadata phases')
    for row in wire['phaseRows']:
        if not isinstance(row, list) or len(row) != 11:
            raise ValueError('Invalid phase row columns')
        action = row[9]
        if not isinstance(action, dict) or set(action) != {'action', 'parameters'} or not isinstance(action['parameters'], list):
            raise ValueError('Phase action must be exactly one named operation object')
        parameters = []
        for param in action['parameters']:
            if not isinstance(param, dict) or set(param) != {'name', 'type', 'value'}:
                raise ValueError('Operation parameter must have name/type/value')
            parameters.append([param['name'], param['type'], param['value']])
        row[9] = [action['action'], parameters]
    return rows.decode(wire)


def descriptor():
    from services.deep_research.workflow_units import descriptor as unit_descriptor, META
    result = rows.descriptor()
    canonical = unit_descriptor(META, 7)['schema']['$defs']
    for key in ('operation', 'parameter'):
        result['schema']['$defs'][key] = deepcopy(canonical[key])
    result['name'] = NAME
    return result


def field_feedback(wire):
    result = wire_feedback(wire)
    for i, component in enumerate(wire['componentRows']):
        if component[0] in ('baseline', 'training_data'):
            result['issues'].append({'code': 'wire.component.reserved_name', 'path': f'/componentRows/{i}/0',
                'actual': deepcopy(component[0]), 'expected': 'nonreserved component ID; reserved inputs are not components'})
    for i, row in enumerate(wire['phaseRows']):
        path = f'/phaseRows/{i}/9'; action = row[9]
        if not isinstance(action, dict):
            result['issues'].append({'code': 'wire.operation.object', 'path': path, 'actual': deepcopy(action),
                'expected': 'ONE {action:string,parameters:[{name,type,value}]} object; model must explicitly split multiple operations into phases'})
            continue
        errors = validate_operation(action)
        if errors:
            result['issues'].append({'code': 'wire.operation.invalid', 'path': path,
                'actual': deepcopy(action), 'expected': 'one operation with unique typed parameter names', 'errors': sorted(errors)})
        seen = set()
        for j, param in enumerate(action.get('parameters', []) if isinstance(action.get('parameters'), list) else []):
            if isinstance(param, dict) and isinstance(param.get('name'), str):
                name = param['name']
                if name in seen:
                    result['issues'].append({'code': 'wire.parameter.duplicate_name', 'path': f'{path}/parameters/{j}/name',
                        'actual': name, 'expected': 'unique name within this operation'})
                seen.add(name)
    result['issues'].sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return result
