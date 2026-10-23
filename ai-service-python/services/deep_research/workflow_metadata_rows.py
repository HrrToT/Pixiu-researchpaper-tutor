"""Lossless metadata wire grammar. Decoding supplies no scientific decisions.

This adapter is deliberately independent of runtime selection: existing saved
unit requests and their response grammars remain frozen.
"""
from copy import deepcopy
import json


PHASE_COLUMNS = ('phaseId', 'scope', 'kind', 'groups', 'sharing', 'after',
                 'reads', 'updates', 'outputs', 'action', 'budget')
COMPONENT_COLUMNS = ('componentId', 'appliesTo', 'lifecycle')
LIFECYCLE_COLUMNS = ('scope', 'createAfter', 'disposeAfter')
PARAMETER_COLUMNS = ('name', 'type', 'value')
COMMON = ('sourceRefs', 'baselineMode', 'replicationMode', 'checkpointSelection',
          'unresolved', 'frameIterations')


def enabled(record):
    return (type(record.get('workflowMetadataRowsContractVersion')) is int
            and record['workflowMetadataRowsContractVersion'] == 1
            and type(record.get('workflowContractVersion')) is int
            and record['workflowContractVersion'] == 5
            and type(record.get('executionWorkflowContractVersion')) is int
            and record['executionWorkflowContractVersion'] == 7)


def _json_copy(value):
    # Reject non-JSON containers/keys rather than silently coercing or dropping
    # them. Scalar semantics are still checked by the existing unit validator.
    def check(v):
        if type(v) is dict:
            if any(type(k) is not str for k in v):
                raise ValueError('Metadata keys must be strings')
            for child in v.values():
                check(child)
        elif type(v) is list:
            for child in v:
                check(child)
        elif type(v) not in (str, int, float, bool, type(None)):
            raise ValueError('Metadata must contain JSON values only')
    check(value)
    json.dumps(value, allow_nan=False)
    return deepcopy(value)


def _object(value, columns):
    if type(value) is not dict or set(value) != set(columns):
        raise ValueError('Metadata object fields do not match its columns')
    return [value[k] for k in columns]


def _row(value, columns):
    if type(value) is not list or len(value) != len(columns):
        raise ValueError('Metadata row has the wrong arity')
    return dict(zip(columns, value))


def _list(value):
    if type(value) is not list:
        raise ValueError('Metadata rows must be arrays')
    return value


def _encode_input(value):
    if type(value) is not dict:
        raise ValueError('Timeline input must be an object')
    columns = ('state', 'selector') if 'state' in value else ('phaseId', 'outputId', 'selector')
    return _object(value, columns)


def _decode_input(value):
    _list(value)
    columns = ('state', 'selector') if len(value) == 2 else ('phaseId', 'outputId', 'selector')
    return _row(value, columns)


def encode(metadata):
    metadata = _json_copy(metadata)
    _object(metadata, (*COMMON, 'components', 'phases'))
    wire = {k: metadata[k] for k in COMMON}
    wire['componentRows'] = []
    for component in _list(metadata['components']):
        row = _object(component, COMPONENT_COLUMNS)
        row[2] = _object(row[2], LIFECYCLE_COLUMNS)
        wire['componentRows'].append(row)
    wire['phaseRows'] = []
    for phase in _list(metadata['phases']):
        row = _object(phase, PHASE_COLUMNS)
        row[6] = [_encode_input(v) for v in _list(row[6])]
        action = _object(row[9], ('action', 'parameters'))
        action[1] = [_object(v, PARAMETER_COLUMNS) for v in _list(action[1])]
        row[9] = action
        wire['phaseRows'].append(row)
    return wire


def decode(wire):
    wire = _json_copy(wire)
    _object(wire, (*COMMON, 'componentRows', 'phaseRows'))
    metadata = {k: wire[k] for k in COMMON}
    metadata['components'] = []
    for row in _list(wire['componentRows']):
        component = _row(row, COMPONENT_COLUMNS)
        component['lifecycle'] = _row(component['lifecycle'], LIFECYCLE_COLUMNS)
        metadata['components'].append(component)
    metadata['phases'] = []
    for row in _list(wire['phaseRows']):
        phase = _row(row, PHASE_COLUMNS)
        phase['reads'] = [_decode_input(v) for v in _list(phase['reads'])]
        action = _row(phase['action'], ('action', 'parameters'))
        action['parameters'] = [_row(v, PARAMETER_COLUMNS) for v in _list(action['parameters'])]
        phase['action'] = action
        metadata['phases'].append(phase)
    return metadata


def descriptor():
    """Derive all value bounds/enums from the unchanged version 7 grammar."""
    from services.deep_research.workflow_units import descriptor as unit_descriptor, META
    schema = deepcopy(unit_descriptor(META, 7)['schema'])
    definitions = schema['$defs']

    def tuple_schema(properties, columns):
        return {'type': 'array', 'prefixItems': [deepcopy(properties[k]) for k in columns],
                'minItems': len(columns), 'maxItems': len(columns)}

    definitions['lifecycle'] = tuple_schema(definitions['lifecycle']['properties'], LIFECYCLE_COLUMNS)
    definitions['timelineInput']['anyOf'] = [
        tuple_schema(v['properties'], tuple(v['required'])) for v in definitions['timelineInput']['anyOf']]
    definitions['parameter']['anyOf'] = [
        tuple_schema(v['properties'], PARAMETER_COLUMNS) for v in definitions['parameter']['anyOf']]
    definitions['operation'] = tuple_schema(definitions['operation']['properties'], ('action', 'parameters'))
    definitions['phase'] = tuple_schema(definitions['phase']['properties'], PHASE_COLUMNS)
    properties = schema['properties']
    component = properties.pop('components')
    component['items'] = tuple_schema(component['items']['properties'], COMPONENT_COLUMNS)
    properties['componentRows'] = component
    properties['phaseRows'] = properties.pop('phases')
    schema['required'] = [*COMMON, 'componentRows', 'phaseRows']
    return {'type': 'json_schema', 'name': 'workflow_metadata_rows_v1', 'schema': schema}


POLICY = (
    'Output metadata in the exact workflow_metadata_rows_v1 columns. '
    'componentRows columns: [componentId,appliesTo,[scope,createAfter,disposeAfter]]. '
    'phaseRows columns: [phaseId,scope,kind,groups,sharing,after,reads,updates,outputs,action,budget]. '
    'Each read is [state,selector] or [phaseId,outputId,selector]. '
    'Each action is [action,[[name,type,value],...]]. All other fields keep their object grammar. '
    'Retain every selected phase, parameter, dependency, state reference and budget. '
    'baseline is the reserved complete baseline prelude handle; a separate mutable copy, if needed, '
    'must have an explicit recipe in later initialization. '
    'createAfter and disposeAfter reference phase IDs only, never component IDs. '
    'Initializer dependencies between components belong to initializer inputs and component order. '
    'Rows are only an encoding, not approval or permission to omit required scientific values.'
)
