from copy import deepcopy

import pytest

from services.deep_research.selection import distinct_evidence_candidates


def row(key):
    return {'evidenceId': key, 'sourceWorkId': 'paper', 'sourceVersionId': 'v1',
            'quote': 'Same observation.', 'sourceContext': 'Exact surrounding passage.',
            'location': {'page': 2}, 'conditions': {'device': 'GPU A'},
            'obligationIds': ['o']}


def test_duplicate_ids_do_not_displace_a_later_distinct_candidate_or_modify_storage():
    rows = [row('e1'), row('e2'), {**row('e3'), 'quote': 'Different method passage.'}]
    before = deepcopy(rows)
    assert [r['evidenceId'] for r in distinct_evidence_candidates(rows)] == ['e1', 'e3']
    assert rows == before


@pytest.mark.parametrize('field,value', [
    ('sourceWorkId', 'another-paper'), ('sourceVersionId', 'v2'),
    ('location', {'page': 3}), ('conditions', {'device': 'GPU B'}),
    ('obligationIds', ['different-question']), ('sourceContext', 'Different subject.')])
def test_distinct_provenance_permissions_and_conditions_are_never_deduplicated(field, value):
    rows = [row('e1'), {**row('e2'), field: value}]
    assert distinct_evidence_candidates(rows) == rows


@pytest.mark.parametrize('field', ['sourceWorkId', 'sourceVersionId'])
def test_missing_identity_is_not_assumed_to_mean_the_same_source(field):
    rows = [{**row('e1'), field: ''}, {**row('e2'), field: ''}]
    assert distinct_evidence_candidates(rows) == rows
