"""Shared model-authored type declarations, before any state is initialized.

Opt-in candidate (server default remains disabled). A declaration is
not an allocated instance, an available input, or scientific approval. Existing
lifecycle, initializer and scientific checks remain independently mandatory.
"""
from copy import deepcopy

from services.deep_research.contracts import digest

VERSION = 1
MAX_BYTES = 16384


def descriptor(version=1, *, metadata=None):
    """No paper-specific variables, encodings, dimensions or values supplied."""
    if type(version) is not int or version not in (1, 2, 3, 4):
        raise ValueError('Unsupported representation version')
    if version == 4:
        from services.deep_research.workflow_representation_slots import descriptor as slots
        return slots(metadata)
    if version == 3:
        from services.deep_research.workflow_representation_input_first import descriptor as input_first
        return input_first()
    if version == 2:
        from services.deep_research.workflow_representation_dependencies import descriptor as dependencies
        return dependencies()
    text = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}
    def strings():
        return {'type': 'array', 'items': deepcopy(text), 'uniqueItems': True, 'maxItems': 128}
    provenance = {'origin': {'enum': ['paper', 'proposal']}, 'sourceRefs': strings()}
    selection = {'entity': deepcopy(text), 'fields': {**strings(), 'minItems': 1}, 'axis': deepcopy(text)}
    axis = {'anyOf': [obj({'state': deepcopy(text), **deepcopy(selection)}),
                      obj({'phaseId': deepcopy(text), 'outputId': deepcopy(text), **deepcopy(selection)})]}
    state = obj({'name': deepcopy(text), 'dtype': deepcopy(text),
                 'shape': {'type': 'array', 'maxItems': 16, 'items': {'anyOf': [
                     {'type': 'integer', 'minimum': 1}, axis]}},
                 'quantity': deepcopy(text), 'encoding': deepcopy(text),
                 'conventionRefs': strings(), **deepcopy(provenance)})
    convention = obj({'name': deepcopy(text), 'definition': deepcopy(text), **deepcopy(provenance)})
    target = obj({'target': deepcopy(text), 'states': {
        'type': 'array', 'minItems': 1, 'maxItems': 128, 'items': state}})
    schema = obj({'sourceRefs': strings(), 'conventions': {
        'type': 'array', 'maxItems': 128, 'items': convention},
        'targets': {'type': 'array', 'maxItems': 9, 'items': target},
        'unresolved': strings()})
    return {'type': 'json_schema', 'name': 'workflow_representation_v1', 'schema': schema}


def _targets(metadata):
    if (not isinstance(metadata, dict) or metadata.get('baselineMode') not in ('train', 'existing')
            or not isinstance(metadata.get('components'), list)):
        raise ValueError('Complete validated workflow metadata required')
    names = [c.get('componentId') if isinstance(c, dict) else None for c in metadata['components']]
    if (any(not isinstance(n, str) or not n.strip() or n in ('baseline', 'training_data') for n in names)
            or len(set(names)) != len(names)):
        raise ValueError('Unique validated component identities required')
    return (['baseline'] if metadata['baselineMode'] == 'train' else []) + names


def issues(value, metadata, aliases, *, version=1):
    """Structural/provenance consistency only; do not infer scientific validity."""
    import json
    from jsonschema import Draft202012Validator
    result = []
    expected = _targets(metadata)
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return [{'code': 'representation.json', 'path': ''}]
    if len(raw) > MAX_BYTES:
        return [{'code': 'representation.capacity', 'path': ''}]
    # V3 native indices are expanded losslessly before canonical validation.
    for error in Draft202012Validator(descriptor(2 if version in (3,4) else version)['schema']).iter_errors(value):
        path = '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in error.absolute_path)
        result.append({'code': 'representation.schema', 'path': path})
    if any(e['code'] == 'representation.schema' for e in result):
        return result
    if [t['target'] for t in value['targets']] != expected:
        result.append({'code': 'representation.target_coverage', 'path': '/targets'})
    conventions = value['conventions']
    convention_names = [c['name'] for c in conventions]
    if len(set(convention_names)) != len(convention_names):
        result.append({'code': 'representation.duplicate_convention', 'path': '/conventions'})
    known = set(aliases)
    union = set()
    entries = [(f'/conventions/{i}', c) for i, c in enumerate(conventions)]
    for i, target in enumerate(value['targets']):
        if version in (2, 3, 4):
            entries += [(f'/targets/{i}/inputDependencies/{j}', d)
                        for j,d in enumerate(target['inputDependencies'])]
        names = [s['name'] for s in target['states']]
        if len(set(names)) != len(names):
            result.append({'code': 'representation.duplicate_state', 'path': f'/targets/{i}/states'})
        for j, state in enumerate(target['states']):
            path = f'/targets/{i}/states/{j}'
            entries.append((path, state))
            # JSON Schema treats 3.0 as an integer. The canonical state contract
            # requires actual integers, so keep the Python representation strict.
            for k, dimension in enumerate(state['shape']):
                if not isinstance(dimension, dict) and type(dimension) is not int:
                    result.append({'code': 'representation.dimension_type', 'path': path + f'/shape/{k}'})
            if set(state['conventionRefs']) - set(convention_names):
                result.append({'code': 'representation.unknown_convention', 'path': path + '/conventionRefs'})
    for path, entry in entries:
        refs = set(entry['sourceRefs'])
        union.update(refs)
        if refs - known or (entry['origin'] == 'paper' and not refs):
            result.append({'code': 'representation.provenance', 'path': path + '/sourceRefs'})
    if set(value['sourceRefs']) != union or union - known:
        result.append({'code': 'representation.source_closure', 'path': '/sourceRefs'})
    if version in (2, 3, 4):
        from services.deep_research.workflow_representation_dependencies import issues as dependency_issues
        result += dependency_issues(value, metadata)
    if version in (3, 4):
        from services.deep_research.workflow_representation_input_first import issues as variable_issues
        result += variable_issues(value)
    if version == 4:
        from services.deep_research.workflow_representation_slots import issues as encoding_issues
        result += encoding_issues(value)
    return result


def freeze(value, metadata, aliases, *, version=1):
    """Bind a declaration to exact metadata/alias identities, without allocation."""
    if issues(value, metadata, aliases, version=version):
        raise ValueError('Invalid shared representation declaration')
    return {'version': version, 'metadataDigest': digest(metadata), 'aliasesDigest': digest(aliases),
            'value': deepcopy(value), 'valueDigest': digest(value), 'scientificApproval': False}


def verify(saved, metadata, aliases):
    if (not isinstance(saved, dict) or set(saved) != {
            'version', 'metadataDigest', 'aliasesDigest', 'value', 'valueDigest', 'scientificApproval'}
            or type(saved['version']) is not int or saved['version'] not in (1, 2, 3, 4)
            or saved['scientificApproval'] is not False
            or saved['metadataDigest'] != digest(metadata) or saved['aliasesDigest'] != digest(aliases)
            or saved['valueDigest'] != digest(saved['value'])
            or issues(saved['value'], metadata, aliases, version=saved['version'])):
        raise ValueError('Shared representation identity changed')
    return deepcopy(saved['value'])


def initialization_descriptor(saved, metadata, aliases, target):
    """Constrain the existing native initializer grammar to declared types.

    The model still returns every variable and initializer. No decoded field is
    supplied by this compiler. Named dynamic axes remain subject to the binding
    checks below, since input indices are chosen in the same model response.
    """
    from services.deep_research.workflow_initialization_semantics import descriptor as previous
    value = verify(saved, metadata, aliases)
    matches = [t for t in value['targets'] if t['target'] == target]
    if len(matches) != 1:
        raise ValueError('Target not declared in shared representation')
    declarations = matches[0]['states']
    result = previous('baseline' if target == 'baseline' else 'component')
    result['name'] = 'workflow_init_representation_v'+str(saved['version'])+'_' + ('baseline' if target == 'baseline' else 'component')
    schema = result['schema']
    definitions = schema['$defs']
    state_schema = definitions['state']
    axis_schema = state_schema['properties']['shape']['items']['anyOf'][1]
    typed_states = []
    dynamic = False
    for declared in declarations:
        state = deepcopy(state_schema)
        state['properties']['name'] = {'const': declared['name']}
        state['properties']['dtype'] = {'const': declared['dtype']}
        dimensions = []
        for dimension in declared['shape']:
            if type(dimension) is int:
                dimensions.append({'const': dimension})
            else:
                dynamic = True
                dimensions.append(deepcopy(axis_schema))
        state['properties']['shape'] = {'type': 'array',
            **({'prefixItems': dimensions} if dimensions else {}),
            'minItems': len(dimensions), 'maxItems': len(dimensions)}
        typed_states.append(state)
    branches = definitions['initialization']['anyOf']
    if dynamic:
        branches = [b for b in branches if b['properties']['initializationMode']['const'] == 'derive']
        definitions['initialization']['anyOf'] = branches
    for branch in branches:
        branch['properties']['stateDefinitions'] = {'type': 'array', 'prefixItems': deepcopy(typed_states),
            'minItems': len(typed_states), 'maxItems': len(typed_states)}
    schema['properties']['stateSemantics'] = {'const': [
        [s['name'], s['quantity'], s['encoding']] for s in declarations]}
    if saved['version'] in (2, 3, 4):
        from services.deep_research.workflow_representation_dependencies import constrain_initialization
        constrain_initialization(result, matches[0])
    return result


def initialization_issues(saved, metadata, aliases, target, initialization):
    """Check a canonical initializer against frozen types, never create values.

    An input-derived shape must refer to the declared state, entity, selected
    fields and axis meaning. Merely matching an input/axis number is insufficient.
    This does not make that input available: lifecycle checks must still run.
    """
    from services.deep_research.state_initialization import state_definition_issues
    from services.deep_research.workflow_initialization_structured import selection
    from services.deep_research.workflow_initialization_semantics import rows
    value = verify(saved, metadata, aliases)
    matches = [t for t in value['targets'] if t['target'] == target]
    if len(matches) != 1:
        raise ValueError('Target not declared in shared representation')
    if not isinstance(initialization, dict):
        return [{'code': 'representation.initialization', 'path': '/initialization'}]
    states, inputs = initialization.get('stateDefinitions'), initialization.get('inputs')
    if not isinstance(inputs, list):
        return [{'code': 'representation.inputs', 'path': '/initialization/inputs'}]
    result = state_definition_issues(states, inputs)
    if result:
        return result
    declarations = matches[0]['states']
    if [s['name'] for s in states] != [s['name'] for s in declarations]:
        return [{'code': 'representation.state_coverage', 'path': '/initialization/stateDefinitions'}]
    semantics = rows(initialization)
    expected_semantics = [[s['name'], s['quantity'], s['encoding']] for s in declarations]
    if saved['version'] in (2, 3, 4):
        from services.deep_research.workflow_representation_dependencies import initialization_issues as dependency_issues
        result += dependency_issues(matches[0], initialization)
    if semantics != expected_semantics:
        result.append({'code': 'representation.semantics_changed', 'path': '/stateSemantics'})
    for i, (state, declared) in enumerate(zip(states, declarations)):
        path = f'/initialization/stateDefinitions/{i}'
        if state['dtype'] != declared['dtype']:
            result.append({'code': 'representation.dtype_changed', 'path': path + '/dtype'})
        same = len(state['shape']) == len(declared['shape'])
        if same:
            for actual, dimension in zip(state['shape'], declared['shape']):
                if type(dimension) is int:
                    same = type(actual) is int and actual == dimension
                elif isinstance(actual, dict):
                    inp = inputs[actual['inputIndex']]
                    selected = selection(inp.get('selector')) if isinstance(inp, dict) else None
                    source_keys = ('state',) if 'state' in dimension else ('phaseId', 'outputId')
                    same = (selected is not None and all(inp.get(k) == dimension[k] for k in source_keys)
                            and selected['entity'] == dimension['entity']
                            and selected['fields'] == dimension['fields']
                            and actual['axis'] < len(selected['axes'])
                            and selected['axes'][actual['axis']] == dimension['axis'])
                else:
                    same = False
                if not same:
                    break
        if not same:
            result.append({'code': 'representation.shape_changed', 'path': path + '/shape'})
    return result
