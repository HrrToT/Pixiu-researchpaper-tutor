"""Metadata v22: same authored values, shared identical schema fragments.

Only local $defs references are factored. Literal const/enum/default data is
never traversed as schema. No change to semantic decoding or scientific gates.
"""
from collections import Counter
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_evaluation_groups as grouped

NAME = 'typed_evaluation_groups_compact_v1'
POLICY = grouped.POLICY.replace(
    'Reads use state or prior step/output stage, never future results.',
    'Reads: state/selector OR prior stepIndex/outputStage/outputId/selector. '
    'outputStage=operation for primitives, measurement|record for observe; match its outputId, never future results.')
decode = grouped.decode
complete_scaffolding = grouped.complete_scaffolding
field_feedback = grouped.field_feedback


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def compact_schema(schema):
    """Factor exact repeated schema objects; keep the original if not smaller."""
    counts = Counter(); fragments = {}

    def children(item, visit):
        result = deepcopy(item)
        for key in ('$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'):
            if key in result:
                result[key] = {name: visit(child) for name, child in result[key].items()}
        for key in ('items', 'additionalProperties', 'contains', 'propertyNames',
                    'not', 'if', 'then', 'else', 'unevaluatedProperties', 'unevaluatedItems'):
            if key in result and isinstance(result[key], (dict, bool)):
                result[key] = visit(result[key])
        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            if key in result:
                result[key] = [visit(child) for child in result[key]]
        return result

    def count(item):
        if isinstance(item, bool): return item
        if not isinstance(item, dict): raise ValueError('Invalid schema fragment')
        if '$id' in item or '$anchor' in item or '$dynamicAnchor' in item or '$dynamicRef' in item:
            raise ValueError('Scoped schema references cannot be factored')
        if '$ref' in item and not item['$ref'].startswith('#/$defs/'):
            raise ValueError('Only local definition references can be factored')
        key = _json(item); counts[key] += 1; fragments[key] = item
        children(item, count)
        return item

    count(schema)
    names = {}; occupied = set(schema.get('$defs', {}))
    for key, occurrences in counts.items():
        name = '_' + str(len(names))
        while name in occupied: name += '_'
        reference = _json({'$ref': '#/$defs/' + name})
        if occurrences > 1 and occurrences * (len(key.encode())-len(reference)) > len(key.encode())+len(name)+8:
            names[key] = name; occupied.add(name)
    if not names: return deepcopy(schema)

    def encode(item):
        if isinstance(item, bool): return item
        key = _json(item)
        if key in names: return {'$ref': '#/$defs/' + names[key]}
        return children(item, encode)

    result = children(schema, encode)
    definitions = result.setdefault('$defs', {})
    for key, name in names.items():
        definitions[name] = children(fragments[key], encode)
    return result if len(_json(result).encode()) < len(_json(schema).encode()) else deepcopy(schema)


def descriptor():
    result = grouped.descriptor()
    result['name'] = NAME
    result['schema'] = compact_schema(result['schema'])
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + grouped.typed.COUNT_POLICY + input_text({
        'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY + grouped.typed.COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})
