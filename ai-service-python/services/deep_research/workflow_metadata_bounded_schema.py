"""Metadata v24: equivalent closed step branches with less repeated framing."""
from copy import deepcopy
import string

from services.deep_research import workflow_metadata_reference_context as previous

decode = previous.decode
complete_scaffolding = previous.complete_scaffolding
field_feedback = previous.field_feedback
generation_prompt = previous.generation_prompt
revision_prompt = previous.revision_prompt


def _map(schema, visit):
    if isinstance(schema, bool): return schema
    result = deepcopy(schema)
    if any(k in result for k in ('$id', '$anchor', '$dynamicAnchor', '$dynamicRef')):
        raise ValueError('Scoped schema cannot be rewritten')
    for key in ('$defs', 'properties', 'patternProperties', 'dependentSchemas'):
        if key in result: result[key] = {k: visit(v) for k, v in result[key].items()}
    for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
        if key in result: result[key] = visit(result[key])
    for key in ('anyOf', 'allOf', 'oneOf', 'prefixItems'):
        if key in result: result[key] = [visit(v) for v in result[key]]
    return result


def closed_branches(branches):
    """All fields required + exact property count preserves closed-object choices.

For a branch requiring S, the root requires its common subset and the branch
requires the rest. At most |S| properties then forbids every key outside S.
Shared property constraints apply at root; varying constraints stay in branch.
"""
    if not branches or any(b.get('type') != 'object' or b.get('additionalProperties') is not False
            or set(b.get('required', [])) != set(b.get('properties', {})) for b in branches):
        raise ValueError('Only fully required closed object branches can be factored')
    names = list(dict.fromkeys(k for b in branches for k in b['properties']))
    properties = {}
    for name in names:
        choices = [b['properties'][name] for b in branches if name in b['properties']]
        properties[name] = deepcopy(choices[0]) if all(x == choices[0] for x in choices) else {}
    required = [k for k in branches[0]['required'] if all(k in b['required'] for b in branches)]
    choices = []
    for branch in branches:
        row = {k: deepcopy(v) for k, v in branch.items()
               if k not in ('type', 'properties', 'required', 'additionalProperties')}
        row.update(properties={k: deepcopy(v) for k, v in branch['properties'].items() if v != properties[k]},
                   required=[k for k in branch['required'] if k not in required],
                   maxProperties=min(len(branch['properties']), branch.get('maxProperties', len(branch['properties']))))
        choices.append(row)
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False, 'anyOf': choices}


def normalize_definitions(schema):
    """Resolve aliases and remove unreachable definitions; literals stay literal."""
    definitions = schema.get('$defs', {})
    def name(ref):
        prefix = '#/$defs/'
        if not isinstance(ref, str) or not ref.startswith(prefix) or '/' in ref[len(prefix):]:
            raise ValueError('Only whole local definitions are supported')
        key = ref[len(prefix):].replace('~1', '/').replace('~0', '~')
        if key not in definitions: raise ValueError('Missing schema definition')
        return key
    def pointer(key): return '#/$defs/' + key.replace('~', '~0').replace('/', '~1')
    def resolve(ref):
        key = name(ref); seen = set()
        while isinstance(definitions[key], dict) and set(definitions[key]) == {'$ref'}:
            if key in seen: raise ValueError('Cyclic schema aliases')
            seen.add(key); key = name(definitions[key]['$ref'])
        return key
    def rewrite(item):
        result = _map(item, rewrite)
        if isinstance(result, dict) and '$ref' in result: result['$ref'] = pointer(resolve(result['$ref']))
        return result
    result = rewrite(schema); definitions = result.pop('$defs', {})
    needed = set()
    def reachable(item):
        if isinstance(item, dict) and '$ref' in item:
            key = name(item['$ref'])
            if key not in needed:
                needed.add(key); reachable(definitions[key])
        _map(item, reachable)
        return item
    reachable(result)
    alphabet = string.ascii_letters + string.digits
    names = {k: alphabet[i] if i < len(alphabet) else '_'+str(i)
             for i, k in enumerate(k for k in definitions if k in needed)}
    def rename(item):
        row = _map(item, rename)
        if isinstance(row, dict) and '$ref' in row: row['$ref'] = pointer(names[name(row['$ref'])])
        return row
    result = rename(result)
    result['$defs'] = {names[k]: rename(v) for k, v in definitions.items() if k in needed}
    return result


def descriptor():
    from services.deep_research.workflow_metadata_compact_transport import _json
    result = previous.descriptor()
    schema = deepcopy(result['schema'])
    schema['$defs']['step'] = closed_branches(schema['$defs']['step']['anyOf'])
    schema = normalize_definitions(schema)
    if len(_json(schema).encode()) < len(_json(result['schema']).encode()): result['schema'] = schema
    result['name'] = 'metadata_steps_v24'
    return result
