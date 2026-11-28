"""Do not equate a successful HTTP response with native schema compliance."""
from copy import deepcopy
import json

import pytest

from services.deep_research.native_schema_receipt import annotate
from services.deep_research.contracts import digest
from llm.responses_transport import API_KEY


def options(schema=None):
    return {API_KEY: 'responses', 'response_format': {'type': 'json_schema', 'name': 'numeric_shape',
        'schema': schema if schema is not None else {'type': 'object', 'properties': {
            'shape': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}}},
            'required': ['shape'], 'additionalProperties': False}}}


def response(value, *, finish='stop'):
    return {'content': json.dumps(value), 'rawContent': json.dumps(value), 'finishReason': finish,
            'usage': {'total_tokens': 12}, 'structuredOutput': {'requestedFormat': 'json_object'}}


def test_valid_schema_receipt_is_not_provider_enforcement_or_scientific_approval():
    r, o = response({'shape': [3, 4]}), options()
    before = deepcopy((r, o)); actual = annotate(r, o)
    receipt = actual['structuredOutput']['nativeSchema']
    assert receipt['status'] == 'valid' and receipt['issues'] == []
    assert receipt['schemaDigest'] == digest(o['response_format']['schema'])
    assert actual['structuredOutput']['requestedFormat'] == 'json_schema'
    assert receipt['providerSchemaEnforcementVerified'] is False and receipt['scientificApproval'] is False
    assert actual['rawContent'] == r['rawContent'] and actual['usage'] == r['usage']
    assert (r, o) == before


def test_returned_string_dimensions_are_recorded_as_invalid_not_coerced():
    r = response({'shape': ['num_gaussians', '59']})
    actual = annotate(r, options())
    receipt = actual['structuredOutput']['nativeSchema']
    assert receipt['status'] == 'invalid'
    assert receipt['issues'] == [{'rule': 'type', 'path': '/shape/0'}, {'rule': 'type', 'path': '/shape/1'}]
    assert actual['content'] == r['content'] and actual['rawContent'] == r['rawContent']
    assert 'num_gaussians' not in json.dumps(receipt)


@pytest.mark.parametrize('finish', ['length', 'responses_failed', None])
def test_noncompleted_output_cannot_claim_schema_compliance(finish):
    assert annotate(response({'shape': [3]}, finish=finish), options())[
        'structuredOutput']['nativeSchema']['status'] == 'not_checked_output_status'


@pytest.mark.parametrize('raw', ['{', '```json\n{"shape":[3]}\n```', None, '{"shape":[NaN]}'])
def test_malformed_or_wrapped_raw_output_is_never_repaired_for_the_receipt(raw):
    r = response({'shape': [3]}); r['rawContent'] = raw
    assert annotate(r, options())['structuredOutput']['nativeSchema']['status'] == 'invalid_json'


def test_local_refs_are_validated_and_external_refs_never_fetch(monkeypatch):
    import requests
    def forbidden(*args, **kwargs): raise AssertionError('No network in a receipt')
    monkeypatch.setattr(requests, 'get', forbidden)
    schema = {'$defs': {'positive': {'type': 'integer', 'minimum': 1}}, '$ref': '#/$defs/positive'}
    assert annotate(response(2), options(schema))['structuredOutput']['nativeSchema']['status'] == 'valid'
    external = {'$ref': 'https://not-allowed.invalid/schema'}
    assert annotate(response(2), options(external))['structuredOutput']['nativeSchema']['status'] == 'invalid_schema'


def test_invalid_server_schema_is_distinct_from_an_invalid_answer():
    assert annotate(response(2), options({'type': 'made_up'}))[
        'structuredOutput']['nativeSchema']['status'] == 'invalid_schema'


def test_failure_details_are_bounded_without_source_values():
    schema = {'type': 'array', 'items': {'type': 'integer'}}
    receipt = annotate(response(['secret fixture text'] * 100), options(schema))['structuredOutput']['nativeSchema']
    assert receipt['status'] == 'invalid' and len(receipt['issues']) == 8 and receipt['issuesTruncated']
    assert 'secret fixture text' not in json.dumps(receipt)


def test_legacy_non_native_responses_are_returned_unchanged():
    r = response({'shape': [3]})
    assert annotate(r, {'response_format': {'type': 'json_object'}}) is r


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_actual_http_and_ledger_keeps_schema_receipt_without_resend(tmp_path, monkeypatch, scenario):
    import test_deep_research_workflow_representation_stage as integration
    from services.deep_research.workflow_representation_stage import NODE
    integration.test_actual_provider_payload_ledger_identity_capacity_and_unknown_no_resend(
        tmp_path, monkeypatch, NODE, scenario)
    if scenario == 'success':
        from services.deep_research.repository import DeepResearchRepository
        repo = DeepResearchRepository(tmp_path/'calls.sqlite3')
        call = repo.list_calls('r')[0]
        assert call['status'] == 'succeeded' and call['settled']
        receipt = call['result']['structuredOutput']['nativeSchema']
        assert receipt['status'] == 'invalid'  # HTTP fixture {} lacks all declaration fields.
        assert call['result']['rawContent'] == '{}'
        assert receipt['schemaDigest'] == digest(integration.options_for_record(
            repo.require_run('r'), NODE, {})['response_format']['schema'])
