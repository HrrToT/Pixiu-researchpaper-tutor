from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.graph import make_synthesize_node
from services.deep_research.synthesis_container import normalize_synthesis_container


def mixed():
    return [{'title': '核心判断', 'claimIds': ['c1', 'c2']},
            {'claimId': 'c1', 'text': 'A proposed diagnostic.', 'kind': 'proposal', 'evidenceRefs': [],
             'conditions': {'scope': 'limited'}, 'executionSpec': {'threshold': 0.25}},
            {'claimId': 'c2', 'text': 'Exact original finding.', 'kind': 'reported', 'evidenceRefs': ['original-id']}]


def test_unambiguous_container_conversion_preserves_every_claim_field_and_reference():
    value = mixed(); before = deepcopy(value)
    normalized, kind = normalize_synthesis_container(value)
    assert kind == 'mixed_section_claim_array'
    assert normalized == {'sections': value[:1], 'claims': value[1:]}
    normalized['claims'][0]['executionSpec']['threshold'] = 99
    assert value == before


@pytest.mark.parametrize('change', ['unknown_row', 'ambiguous_row', 'duplicate_id', 'duplicate_ref',
                                   'foreign_ref', 'unmapped_claim', 'only_claims', 'only_sections'])
def test_ambiguous_or_incomplete_mixed_containers_are_not_partially_recovered(change):
    value = mixed()
    if change == 'unknown_row': value.append({'note': 'Do not silently discard me.'})
    elif change == 'ambiguous_row': value[1]['title'] = 'Both section and claim'
    elif change == 'duplicate_id': value[2]['claimId'] = 'c1'
    elif change == 'duplicate_ref': value[0]['claimIds'].append('c1')
    elif change == 'foreign_ref': value[0]['claimIds'].append('foreign')
    elif change == 'unmapped_claim': value[0]['claimIds'].remove('c2')
    elif change == 'only_claims': value = value[1:]
    elif change == 'only_sections': value = value[:1]
    before = deepcopy(value)
    assert normalize_synthesis_container(value) == (None, None)
    assert value == before


def test_canonical_container_keeps_existing_claim_validation_separate():
    value = {'claims': [{'unvalidated': 'Still requires ordinary claim checks.'}]}
    assert normalize_synthesis_container(value) == (value, 'object')


@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_graph_uses_one_received_response_and_does_not_publish_or_retry_during_normalization(finish):
    record = {'question': 'Propose a diagnostic.', 'materials': [],
              'state': {'outputKind': 'direction_survey', 'plan': [], 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    invoke = Mock(return_value={'content': json.dumps(mixed()), 'finishReason': finish})
    result = make_synthesize_node(invoke, update)({'run_id': 'r'})
    invoke.assert_called_once()
    if finish == 'length':
        assert result['error_code'] == 'invalid_synthesis_response'
        assert 'reportBody' not in record['state']
    else:
        assert record['state']['synthesisContainer'] == 'mixed_section_claim_array'
        assert [c['claimId'] for c in record['state']['reportBody']['claims']] == ['c1', 'c2']
        assert 'verifiedReport' not in record['state'] and 'publicationId' not in record['state']
