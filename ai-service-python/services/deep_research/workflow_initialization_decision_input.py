"""Named, exact state decision before losslessly encoded initialization input.

Moves a supplied proposal string; never extracts variables or chooses values.
Only a single typed marker at a fixed path can be restored from the named field.
"""
from copy import deepcopy
import json

MARKER = 'workflowInitializationDecisionInputContractVersion'
LEGEND = ('\nDecode boundInput normally; restore ONLY its '
          'authoritativeInput.unverifiedScientificPlan.protocol.state from unverified stateDecision.\n')
PLACEHOLDER = {'$stateDecision': True}


def enabled(record):
    from services.deep_research.workflow_initialization_structured import enabled as structured
    return (isinstance(record, dict) and type(record.get(MARKER)) is int
            and record[MARKER] == 1 and structured(record))


def _protocol(value):
    try:
        result = value['authoritativeInput']['unverifiedScientificPlan']['protocol']
        return result if isinstance(result, dict) else None
    except (KeyError, TypeError): return None


def _decode_body(wire):
    from services.deep_research import shared_strings, nested_tables, workflow_metadata_input
    if not isinstance(wire, dict): raise ValueError('Bound input must be an object')
    value = deepcopy(wire)
    if set(value) == {'strings','value'}:
        value = nested_tables.unpack(shared_strings.unpack(value))
    if isinstance(value, dict) and set(value) == {'keys','value'}:
        value = workflow_metadata_input.unpack(value)
    return value


def restore(envelope):
    if (not isinstance(envelope, dict) or set(envelope) != {'stateDecision','boundInput'}
            or not isinstance(envelope['stateDecision'], str) or not envelope['stateDecision'].strip()):
        raise ValueError('Exact named decision input required')
    value = _decode_body(envelope['boundInput']); protocol = _protocol(value)
    marker = protocol.get('state') if protocol is not None else None
    if (not isinstance(marker, dict) or set(marker) != {'$stateDecision'}
            or marker['$stateDecision'] is not True):
        raise ValueError('Decision marker missing or changed at its bound path')
    protocol['state'] = envelope['stateDecision']
    return value


def input_text(value):
    from services.deep_research.workflow_metadata_input import input_text as original
    from services.deep_research.contracts import digest
    protocol = _protocol(value)
    if protocol is None or not isinstance(protocol.get('state'), str) or not protocol['state'].strip():
        return original(value)
    modified = deepcopy(value); decision = protocol['state']
    _protocol(modified)['state'] = deepcopy(PLACEHOLDER)
    body, _, legend = original(modified).partition('\n')
    envelope = {'stateDecision':decision, 'boundInput':json.loads(body)}
    if digest(restore(envelope)) != digest(value):
        raise ValueError('Named state decision changed bound input')
    return json.dumps(envelope, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n' + legend + LEGEND
