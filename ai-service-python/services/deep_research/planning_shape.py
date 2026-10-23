"""One reversible representation move; never fill or reinterpret plan values."""
from copy import deepcopy

from services.deep_research.contracts import digest


def enabled(record):
    return (isinstance(record, dict)
        and type(record.get('structuredOutputContractVersion')) is int
        and record['structuredOutputContractVersion'] == 15
        and type(record.get('experimentPlanEncodingContractVersion')) is int
        and record['experimentPlanEncodingContractVersion'] == 7)


def response_value(response, parse, record):
    value = parse(response.get('content', '')) if isinstance(response, dict) else None
    if not enabled(record):
        return value, None
    original = deepcopy(value)
    moves = []
    protocol_keys = {'intervention', 'data', 'state', 'poseError', 'measurement'}
    if (isinstance(value, dict)
            and set(value) == {'sourceRefs', 'protocol', 'unresolved', 'pairingBudget'}
            and isinstance(value['protocol'], dict)
            and set(value['protocol']) == protocol_keys
            and isinstance(value['pairingBudget'], dict)):
        value = deepcopy(value)
        value['protocol']['pairingBudget'] = value.pop('pairingBudget')
        restored = deepcopy(value)
        restored['pairingBudget'] = restored['protocol'].pop('pairingBudget')
        if restored != original:
            raise ValueError('Planning shape move is not reversible')
        moves = [{'from': '/pairingBudget', 'to': '/protocol/pairingBudget'}]
    return value, {'version': 1, 'rawResponseDigest': digest(response),
        'originalValueDigest': digest(original), 'normalizedValueDigest': digest(value),
        'moves': moves, 'scientificApproval': False}


def audit(response, parse, record):
    if not enabled(record):
        return None
    try:
        return response_value(response, parse, record)[1]
    except (ValueError, TypeError, RecursionError):
        return {'version': 1, 'rawResponseDigest': digest(response),
            'parseable': False, 'moves': [], 'scientificApproval': False}
