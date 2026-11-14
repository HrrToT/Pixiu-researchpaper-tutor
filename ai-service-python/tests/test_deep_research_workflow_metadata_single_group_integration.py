from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import digest, DeepResearchError
from services.deep_research.workflow_metadata_single_group import decode, NAME
from services.deep_research.workflow_metadata_repair import prepare
from test_deep_research_workflow_metadata_single_group import authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def failed_scalar_unit():
    wire = authored(); wire['steps'][2]['group'] = 'both'
    raw = response(wire)
    return {'request': {'prompt': 'original', 'extra': {}}, 'response': raw,
            'responseDigest': digest(raw), 'value': None, 'valueDigest': digest(None),
            'status': 'invalid_response', 'errors': ['unit.json']}


def test_generation_one_revision_full_initialization_and_recovery():
    wire = authored(); bad = deepcopy(wire); bad['steps'][2]['group'] = 'both'
    r, original, invoke, run = setup_repair([response(bad), response(wire), *map(response, explicit_initializers())])
    r['workflowMetadataRepairContractVersion'] = 14
    saved = run(); revision = saved['metadataRepair']
    assert saved['status'] == 'ready' and revision['value'] == decode(wire)
    assert not saved['scientificApproval'] and invoke.call_count == 5
    meta = saved['units']['metadata']
    assert meta['request']['extra']['response_format']['name'] == NAME
    assert meta['response'] == response(bad) and meta['value'] is None
    payload = input_value(revision['request']['prompt'])
    assert payload['invalidMetadata'] == bad
    assert any(x['path'] == '/steps/2/group' and x['actual'] == 'both'
               for x in payload['fieldFeedback']['issues'])
    assert payload['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    before = deepcopy(saved); assert run() == before and invoke.call_count == 5


def test_invalid_received_revision_stays_invalid_and_is_never_sent_twice():
    r, _, _, _ = setup_repair(); r['workflowMetadataRepairContractVersion'] = 14
    sender = Mock(return_value=response(authored()))
    # Invalid actual selection is retained, never split into two valid arms.
    invalid = authored(); invalid['steps'][2]['group'] = ['0', '1']
    sender.return_value = response(invalid); store = {}
    def run():
        return prepare(r, source_data='{}', failed=failed_scalar_unit(), aliases={'E1': 'owned'},
                       existing=store.get('revision'), invoke=sender,
                       checkpoint=lambda v: store.update(revision=deepcopy(v)))
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert sender.call_count == 1 and store['revision']['value'] is None
    assert store['revision']['response'] == response(invalid)
