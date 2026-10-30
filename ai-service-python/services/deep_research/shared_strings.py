"""Lossless JSON string sharing for bounded inputs, never model output repair."""
from collections import Counter
from copy import deepcopy
import json


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8'))


def pack(value):
    counts = Counter()
    def visit(item):
        if isinstance(item, str): counts[item] += 1
        elif isinstance(item, list):
            for child in item: visit(child)
        elif isinstance(item, dict):
            for child in item.values(): visit(child)
    visit(value)
    strings = []
    for string, count in counts.items():
        if count > 1 and count * (_size(string) - _size({'$': len(strings)})) > _size(string) + 20:
            strings.append(string)
    indices = {string: i for i, string in enumerate(strings)}
    def encode(item):
        if isinstance(item, str): return {'$': indices[item]} if item in indices else item
        if isinstance(item, list): return [encode(child) for child in item]
        if isinstance(item, dict):
            result = {key: encode(child) for key, child in item.items()}
            return {'~': result} if {'$', '~'} & set(item) else result
        return deepcopy(item)
    return {'strings': strings, 'value': encode(value)}


def unpack(wire):
    if (not isinstance(wire, dict) or set(wire) != {'strings', 'value'}
            or not isinstance(wire['strings'], list)
            or any(not isinstance(s, str) for s in wire['strings'])):
        raise ValueError('Invalid shared string table')
    strings = wire['strings']
    def decode(item):
        if isinstance(item, dict):
            if set(item) == {'$'}:
                index = item['$']
                if type(index) is not int or not 0 <= index < len(strings):
                    raise ValueError('Invalid shared string reference')
                return strings[index]
            if set(item) == {'~'}:
                if not isinstance(item['~'], dict): raise ValueError('Invalid shared string escape')
                return {key: decode(child) for key, child in item['~'].items()}
            if {'$', '~'} & set(item): raise ValueError('Unescaped shared string marker')
            return {key: decode(child) for key, child in item.items()}
        if isinstance(item, list): return [decode(child) for child in item]
        return deepcopy(item)
    return decode(wire['value'])


LEGEND = ('Input sharing only: {"$":i} restores strings[i] as an exact string VALUE; '
          '{"~":object} escapes a literal object. After string restoration, '
          '{"@":[columns,rows]} restores an object list and {"!":object} escapes a literal object. '
          'Restore all original values before interpreting them. Output uses ordinary schema values, not references.')


def input_text(value):
    from services.deep_research.nested_tables import pack as tables, unpack as untables
    from services.deep_research.contracts import digest
    encode = lambda v: json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    wire = pack(tables(value))
    if digest(untables(unpack(wire))) != digest(value):
        raise ValueError('Shared input failed its lossless round trip')
    shared = encode(wire) + '\n' + LEGEND
    literal = encode(value)
    return shared if len(shared.encode('utf8')) < len(literal.encode('utf8')) else literal
