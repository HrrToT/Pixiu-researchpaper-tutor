"""Local schema compliance receipt, never a provider or scientific guarantee."""
from itertools import islice
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from llm.responses_transport import API_KEY
from services.deep_research.contracts import digest


def _deny_retrieval(uri):
    raise NoSuchResource(ref=uri)


def _deny_constant(value):
    raise ValueError('Non-JSON numeric constant')


def annotate(response, options):
    """Check the exact raw answer against the fingerprinted request's schema.

    This records what happened without repairing content, granting scientific
    approval, retrying, or changing the call's settlement and existing gates.
    Old cached calls return before this function and retain their old receipts.
    """
    if options.get(API_KEY) != 'responses':
        return response
    fmt = options['response_format']
    result = {**response, 'structuredOutput': {**response.get('structuredOutput', {}),
                                              'requestedFormat': 'json_schema'}}
    receipt = {'version': 1, 'schemaName': fmt['name'], 'schemaDigest': digest(fmt['schema']),
               'providerSchemaEnforcementVerified': False, 'scientificApproval': False}
    result['structuredOutput']['nativeSchema'] = receipt
    if response.get('finishReason') != 'stop':
        receipt['status'] = 'not_checked_output_status'
        return result
    raw = response.get('rawContent', response.get('content'))
    if not isinstance(raw, str):
        receipt['status'] = 'invalid_json'
        return result
    try:
        value = json.loads(raw, parse_constant=_deny_constant)
    except (ValueError, RecursionError):
        receipt['status'] = 'invalid_json'
        return result
    try:
        Draft202012Validator.check_schema(fmt['schema'])
        validator = Draft202012Validator(fmt['schema'], registry=Registry(retrieve=_deny_retrieval))
        errors = list(islice(validator.iter_errors(value), 9))
    except (SchemaError, Unresolvable, ValueError, TypeError, RecursionError):
        receipt['status'] = 'invalid_schema'
        return result
    receipt['status'] = 'invalid' if errors else 'valid'
    receipt['issues'] = [{'rule': str(error.validator)[:64], 'path': ('/' + '/'.join(
        str(part).replace('~', '~0').replace('/', '~1') for part in error.absolute_path))[:256]
        if error.absolute_path else ''} for error in errors[:8]]
    receipt['issuesTruncated'] = len(errors) > 8
    return result
