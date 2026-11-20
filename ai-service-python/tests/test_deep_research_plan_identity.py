from copy import deepcopy
import hashlib
import json

import pytest

from services.deep_research.coverage import coverage_gaps, validate_plan
from services.deep_research.graph import make_plan_node
from services.deep_research.plan_identity import normalize_generated_obligation_ids


def plan():
    return [{'itemId': name, 'question': question, 'dependencies': deps,
             'obligations': [{'obligationId': 'o1', 'question': question,
                              'requiredSources': [source]}]}
            for name, question, source, deps in [
                ('method', 'How does the mechanism operate?', 'paper-a', []),
                ('comparison', 'Which comparison is supported?', 'paper-b', ['method'])]]


def test_cross_item_reuse_preserves_questions_sources_and_dependency_with_unique_routing():
    original = plan()
    before = deepcopy(original)
    normalized, changes = normalize_generated_obligation_ids(original)
    validate_plan(normalized)
    assert original == before
    assert len(changes) == 2
    ids = [item['obligations'][0]['obligationId'] for item in normalized]
    assert len(set(ids)) == 2 and 'o1' not in ids
    for old, new in zip(original, normalized):
        restored = deepcopy(new)
        restored['obligations'][0]['obligationId'] = 'o1'
        assert restored == old
    # Evidence for one source/question cannot satisfy the other despite the
    # model originally assigning both the same local label.
    gaps = coverage_gaps(normalized, [{'obligationId': ids[0], 'sourceWorkId': 'paper-a',
                                      'state': 'supported'}], ['paper-a', 'paper-b'])
    assert len(gaps) == 1 and gaps[0]['obligationId'] == ids[1]
    assert gaps[0]['sourceWorkId'] == 'paper-b'
    assert normalize_generated_obligation_ids(original) == (normalized, changes)


def test_unique_saved_labels_are_unchanged_and_normalization_is_idempotent():
    original = plan()
    original[1]['obligations'][0]['obligationId'] = 'o2'
    assert normalize_generated_obligation_ids(original) == (original, [])
    normalized, _ = normalize_generated_obligation_ids(plan())
    assert normalize_generated_obligation_ids(normalized) == (normalized, [])


@pytest.mark.parametrize('malformation', ['same_item_duplicate', 'duplicate_item', 'cycle', 'unknown_dependency', 'invalid_id'])
def test_normalization_cannot_make_ambiguous_or_invalid_plans_valid(malformation):
    original = plan()
    if malformation == 'same_item_duplicate':
        original[0]['obligations'].append(deepcopy(original[0]['obligations'][0]))
    elif malformation == 'duplicate_item':
        original[1]['itemId'] = original[0]['itemId']
    elif malformation == 'cycle':
        original[0]['dependencies'] = ['comparison']
    elif malformation == 'unknown_dependency':
        original[0]['dependencies'] = ['missing']
    else:
        original[0]['obligations'][0]['obligationId'] = ''
    normalized, _ = normalize_generated_obligation_ids(original)
    with pytest.raises(ValueError):
        validate_plan(normalized)


def test_generated_label_cannot_collide_with_an_existing_valid_label():
    original = plan()
    candidate = 'ob_' + hashlib.sha256(json.dumps(['method', 'o1'], separators=(',', ':')).encode()).hexdigest()[:24]
    original[0]['obligations'].append({'obligationId': candidate, 'question': 'Independent question.'})
    normalized, changes = normalize_generated_obligation_ids(original)
    validate_plan(normalized)
    assert changes[0]['obligationId'] == candidate + '_1'
    assert normalized[0]['obligations'][1]['obligationId'] == candidate


def test_new_plan_node_normalizes_before_persisting_without_another_model_call():
    record = {'question': 'Compare mechanisms.', 'materials': [
        {'materialId': 'paper-a'}, {'materialId': 'paper-b'}], 'state': {'outputKind': 'paper_comparison'}}
    calls = []
    def update(_, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(_, node, prompt, *args, **kwargs):
        calls.append(node)
        return {'content': json.dumps(plan())}
    result = make_plan_node(invoke, update, validate_plan)({'run_id': 'r'})
    assert result['plan_ids'] == ['method', 'comparison']
    assert calls == ['plan'] and len(record['state']['planIdNormalization']) == 2
    validate_plan(record['state']['plan'])
