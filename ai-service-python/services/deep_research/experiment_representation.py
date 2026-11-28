"""Versioned representation normalization; no scientific choices or approval."""
from copy import deepcopy

from services.deep_research.group_spec import validate_operation
from services.deep_research.nested_tables import unpack

ROLE_FIELDS = {
    'groups': {'factors'},
    'data': {'dataset', 'scenes', 'split', 'seeds', 'independentUnit', 'replication'},
    'analysis': {'effects', 'uncertainty', 'decision'},
    'controls': {'initialization', 'rendering', 'optimizer', 'otherInterventions'},
    'budget': {'baseline', 'recovery'},
    'hypothesis': {'statement', 'analysisClaimId', 'effectKeys', 'purpose'},
    'steps': {'refs', 'order', 'baselineMode', 'replicationMode', 'baselineInitialization',
        'componentInitializations', 'checkpointSelection', 'records'},
}

GUIDANCE = ('Each executionSpec uses its role fields directly; no role-name wrapper. '
    'Emit actual values, not grammar strings. Operation parameters may be objects or '
    'exact [name,type,value] rows; no inferred values.')


def _parameters(value):
    if isinstance(value, list) and value and all(isinstance(row, list) and len(row) == 3 for row in value):
        return [dict(zip(('name', 'type', 'value'), row)) for row in value], 'operation_parameter_rows'
    if isinstance(value, dict) and set(value) == {'@'}:
        table = value['@']
        if (isinstance(table, list) and len(table) == 2 and isinstance(table[0], list)
                and len(table[0]) == 3 and all(isinstance(key, str) for key in table[0])
                and set(table[0]) == {'name', 'type', 'value'}):
            try:
                return unpack(value), 'operation_parameter_table'
            except (ValueError, TypeError):
                pass
    return None, None


def _operations(role, spec):
    """Visit known operation slots only, never literal values/conditions/metadata."""
    if role == 'groups' and isinstance(spec.get('factors'), list):
        for i, factor in enumerate(spec['factors']):
            if isinstance(factor, dict):
                for key in ('control', 'treatment'):
                    yield ['factors', i, key], factor.get(key)
    elif role == 'controls':
        for key in ('rendering', 'optimizer', 'otherInterventions'):
            yield [key], spec.get(key)
    elif role == 'steps':
        definitions = [(['baselineInitialization'], spec.get('baselineInitialization'))]
        if isinstance(spec.get('componentInitializations'), list):
            definitions += [(['componentInitializations', i], item)
                for i, item in enumerate(spec['componentInitializations'])]
        for path, definition in definitions:
            if not isinstance(definition, dict):
                continue
            yield [*path, 'creation'], definition.get('creation')
            states = definition.get('stateDefinitions')
            for i, state in enumerate(states if isinstance(states, list) else []):
                init = state.get('initializer') if isinstance(state, dict) else None
                if isinstance(init, dict) and init.get('mode') == 'operation':
                    yield [*path, 'stateDefinitions', i, 'initializer', 'rule'], init.get('rule')
        selection = spec.get('checkpointSelection')
        if isinstance(selection, dict) and selection.get('mode') in ('train_loss', 'validation_split'):
            yield ['checkpointSelection', 'rule'], selection.get('rule')


def normalize_spec(role, value):
    spec = deepcopy(value); audit = []
    expected = ROLE_FIELDS.get(role) if isinstance(role, str) else None
    if expected is None or not isinstance(spec, dict):
        return spec, audit
    if set(spec) == {role} and isinstance(spec[role], dict) and set(spec[role]) == expected:
        spec = spec[role]
        audit.append({'path': '/executionSpec', 'kind': 'single_role_wrapper', 'role': role})
    if set(spec) != expected:
        return spec, audit  # Never drop extras or infer missing fields.
    for path, operation in _operations(role, spec):
        if (not isinstance(operation, dict) or set(operation) != {'action', 'parameters'}):
            continue
        parameters, kind = _parameters(operation['parameters'])
        if kind is None:
            continue
        candidate = {**operation, 'parameters': parameters}
        try:
            errors = validate_operation(candidate)
        except (TypeError, ValueError, OverflowError):
            errors = ['invalid_operation']
        if errors:
            continue  # Atomic collection conversion, no partial fixing of bad values.
        operation['parameters'] = parameters
        pointer = '/executionSpec/' + '/'.join(str(key).replace('~', '~0').replace('/', '~1') for key in [*path, 'parameters'])
        audit.append({'path': pointer, 'kind': kind, 'rows': len(parameters)})
    return spec, audit


def normalize_claims(claims):
    result = deepcopy(claims); audit = []
    for claim in result:
        if (not isinstance(claim, dict) or type(claim.get('designContractVersion')) is not int
                or claim['designContractVersion'] != 2 or not isinstance(claim.get('kind'), str)
                or claim['kind'] not in {'proposal', 'suggestion', 'hypothesis'}
                or not isinstance(claim.get('claimId'), str) or not claim['claimId'].strip()
                or not isinstance(claim.get('designRole'), str) or 'executionSpec' not in claim):
            continue
        claim['executionSpec'], changes = normalize_spec(claim['designRole'], claim['executionSpec'])
        audit.extend({'claimId': claim['claimId'], 'designRole': claim['designRole'], **change} for change in changes)
    return result, audit
