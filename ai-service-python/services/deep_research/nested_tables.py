"""Lossless wire tables for repeated object-array keys in experimental configs."""
from copy import deepcopy
import json


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8'))


def pack(value):
    """Keep only byte-saving tables; literal reserved keys are always escaped."""
    if isinstance(value, dict):
        row = {key: pack(item) for key, item in value.items()}
        return {'!': row} if {'@', '!'} & set(value) else row
    if isinstance(value, list):
        rows = [pack(item) for item in value]
        if (value and isinstance(value[0], dict) and not {'@', '!'} & set(value[0])
                and all(isinstance(item, dict) and set(item) == set(value[0]) for item in value)):
            keys = list(value[0])
            table = {'@': [keys, [[row[key] for key in keys] for row in rows]]}
            if _bytes(table) < _bytes(rows):
                return table
        return rows
    return deepcopy(value)


def unpack(value):
    """Proof/debug decoder. Model output must still use ordinary config values."""
    if isinstance(value, dict):
        if set(value) == {'!'}:
            if not isinstance(value['!'], dict):
                raise ValueError('Invalid literal object escape')
            return {key: unpack(item) for key, item in value['!'].items()}
        if set(value) == {'@'}:
            table = value['@']
            if not isinstance(table, list) or len(table) != 2:
                raise ValueError('Invalid nested table')
            keys, rows = table
            if (not isinstance(keys, list) or any(not isinstance(key, str) for key in keys)
                    or len(keys) != len(set(keys)) or not isinstance(rows, list)
                    or any(not isinstance(row, list) or len(row) != len(keys) for row in rows)):
                raise ValueError('Invalid nested table rows')
            return [dict(zip(keys, [unpack(item) for item in row])) for row in rows]
        return {key: unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unpack(item) for item in value]
    return deepcopy(value)


def claim_views(claims):
    return [{**deepcopy(claim), **({'executionSpec': pack(claim['executionSpec'])}
        if 'executionSpec' in claim else {})} for claim in claims]
