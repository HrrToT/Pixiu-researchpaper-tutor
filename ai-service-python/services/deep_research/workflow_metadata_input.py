"""Lossless input-only key sharing for metadata contract 9.

Every original field and value survives. This encoding never processes model
output or changes a workflow decision.
"""
from copy import deepcopy
import json

from services.deep_research import nested_tables, shared_strings

POLICY = (
    'Creation allocates a state before its first read/update; createAfter does not mean '
    'the phase that finished fitting it. A phase cannot update a component whose creation '
    'depends on that same phase. Declare allocation separately from fitting when needed, '
    'and release only after all consumers. Keep unavailable checkpoints unresolved; '
    'the system does not supply an allocation or initialization decision.\n'
)
LEGEND = (
    shared_strings.LEGEND + ' Then keys/value is an input-only field dictionary: '
    'in value, replace EVERY object key k with keys[int(k)], recursively, including '
    'objects in arrays. Do not change array positions or scalar values. '
    'Output uses the ordinary named schema, never numeric field keys.'
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def pack(value):
    keys, indices = [], {}
    def visit(item):
        if isinstance(item, dict):
            row = {}
            for key, child in item.items():
                if not isinstance(key, str): raise ValueError('Input keys must be strings')
                if key not in indices:
                    indices[key] = len(keys); keys.append(key)
                row[str(indices[key])] = visit(child)
            return row
        if isinstance(item, list): return [visit(child) for child in item]
        return deepcopy(item)
    result = visit(value)
    return {'keys': keys, 'value': result}


def unpack(wire):
    if (not isinstance(wire, dict) or set(wire) != {'keys', 'value'}
            or not isinstance(wire['keys'], list)
            or any(not isinstance(k, str) for k in wire['keys'])
            or len(set(wire['keys'])) != len(wire['keys'])):
        raise ValueError('Invalid field dictionary')
    keys = wire['keys']
    def visit(item):
        if isinstance(item, dict):
            row = {}
            for key, child in item.items():
                if (not isinstance(key, str) or not key.isascii() or not key.isdecimal()
                        or str(int(key)) != key or not 0 <= int(key) < len(keys)):
                    raise ValueError('Invalid input field reference')
                row[keys[int(key)]] = visit(child)
            return row
        if isinstance(item, list): return [visit(child) for child in item]
        return deepcopy(item)
    return visit(wire['value'])


def input_text(value):
    from services.deep_research.contracts import digest
    wire = shared_strings.pack(nested_tables.pack(pack(value)))
    restored = unpack(nested_tables.unpack(shared_strings.unpack(wire)))
    if digest(restored) != digest(value): raise ValueError('Input key sharing changed values')
    encoded = _json(wire) + '\n' + LEGEND
    original = shared_strings.input_text(value)
    return encoded if len(encoded.encode('utf8')) < len(original.encode('utf8')) else original
