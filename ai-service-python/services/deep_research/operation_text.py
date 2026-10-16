"""Readable operation values; validation and scientific judgment live elsewhere."""
import json


def operation_text(operation, *, include_action=True):
    parts = [operation['action']] if include_action else []
    for parameter in operation['parameters']:
        value = parameter['value']
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
        parts.append(parameter['name'] + '：' + shown)
    result = '；'.join(parts)
    return ('；' + result) if result and not include_action else result
