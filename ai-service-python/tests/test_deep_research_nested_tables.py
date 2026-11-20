from copy import deepcopy
import json
import random
from unittest.mock import Mock

import pytest

from services.deep_research.nested_tables import pack, unpack
from services.deep_research.experiment_edits import restore_columns
from services.deep_research.repair import _prepare_repair, repair_rejected, _parse_repair_response
from services.deep_research.contracts import DeepResearchError, BudgetExhaustedError
from test_deep_research_shared_experiment_repair import inputs


def prepare(**kw):
    report, checks, evidence = inputs()
    return _prepare_repair(report, checks, evidence, 'One unexecuted whole-stage comparison.',
        shared_experiment_schema=True, experimental_edits=True, experimental_diagnostics=True,
        experimental_nested_tables=True, experimental_intent=3, **kw)


@pytest.mark.parametrize('value', [[], None, True, False, 0, 1, -0.0, {}, {'@': []}, {'!': {'@': 3}},
    [{'@': {'columns': ['x'], 'rows': [[1]]}}, {'@': 'literal'}],
    [{'a': None}, {'b': None}], [{'a': False, 'b': 1}, {'b': 0, 'a': True}],
    {'long_array': [{'name': 'xyz', 'type': 'number', 'value': i} for i in range(8)]}])
def test_nested_tables_roundtrip_values_absence_types_unicode_and_reserved_literal_keys(value):
    before = deepcopy(value); encoded = pack(value); restored = unpack(encoded)
    encode = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert encode(restored) == encode(value) and encode(before) == encode(value)
    assert restored == value  # Explicit JSON comparison above distinguishes true/1.


def test_roundtrip_composes_multiple_nested_tables_without_source_mutation():
    value = [{'parameters': [{'name': '选择/' + str(i), 'type': 'choice', 'value': {'@': [i, None]}}
        for i in range(8)], 'states': [{'name': 'state' + str(i), 'dtype': 'float32',
        'shape': [i+1, 3], 'initializer': {'mode': 'constant', 'value': 0}} for i in range(6)]} for _ in range(4)]
    before = deepcopy(value); encoded = pack(value)
    assert len(json.dumps(encoded).encode()) < len(json.dumps(value).encode())
    assert unpack(encoded) == before == value


def test_deterministic_diverse_json_roundtrips_include_literal_marker_collisions():
    rng = random.Random(705)
    def value(depth):
        if depth == 0: return rng.choice([None, True, False, 0, -1, 1.5, '中文/@!'])
        return rng.choice([lambda: [value(depth-1) for _ in range(rng.randrange(4))],
            lambda: {k: value(depth-1) for k in rng.sample(['@', '!', 'normal', '0', 'a/b', 't~x'], rng.randrange(5))},
            lambda: value(0)])()
    for _ in range(120):
        original = value(4)
        assert json.dumps(unpack(pack(original)), ensure_ascii=False, sort_keys=True) == json.dumps(original, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize('wire', [{'!': []}, {'@': None}, {'@': [[], [], []]},
    {'@': [['x', 'x'], [[1, 2]]]}, {'@': [['x'], [[1, 2]]]}, {'@': [[1], [[2]]]}])
def test_malformed_internal_table_fails_instead_of_silent_data_loss(wire):
    with pytest.raises(ValueError): unpack(wire)


def test_new_prompt_restores_all_original_configs_checks_and_source_texts():
    report, checks, evidence = inputs(); p = prepare()
    decode = lambda label: json.JSONDecoder().raw_decode(p['prompt'].split(label, 1)[1].lstrip())[0]
    claims = restore_columns(decode('Writable original claims:'))
    for original, restored in zip(report['claims'], claims):
        assert original.get('executionSpec') == unpack(restored['executionSpec']) if 'executionSpec' in original else 'executionSpec' not in restored
        assert restored['text'] == original['text'] and restored.get('conditions', {}) == original.get('conditions', {})
    rejection = restore_columns(decode('ALL rejection checks:'))
    assert all(c['additionalChecks'] for c in rejection)
    rows = restore_columns(decode('Exact original evidence/context/table data (lossless column table):'))
    assert rows[0]['quote'] == evidence[0]['quote']
    assert p['nestedTablesVersion'] == 1 and p['originals'] == {c['claimId']: c for c in report['claims']}
    size = len(p['prompt'].encode()); assert prepare(max_prompt_bytes=size)['prompt'] == p['prompt']
    with pytest.raises(BudgetExhaustedError): prepare(max_prompt_bytes=size-1)


def test_model_edits_use_real_paths_and_preserve_full_original_fields():
    p = prepare(); patch = [{'claimId': 'budget', 'edits': [
        {'op': 'replace', 'path': '/executionSpec/baseline/maxBudget', 'value': 70}]}]
    result = _parse_repair_response(p, {'content': json.dumps(patch)}, json.loads, strict_response=True)
    assert result[0]['executionSpec']['baseline']['maxBudget'] == 70
    assert result[0]['executionSpec']['recovery'] == p['originals']['budget']['executionSpec']['recovery']
    patch[0]['edits'][0]['path'] = '/executionSpec/@/0'
    assert _parse_repair_response(p, {'content': json.dumps(patch)}, json.loads, strict_response=True) == []


def test_new_nested_request_is_frozen_before_dispatch_and_cannot_resume_under_old_format():
    report, checks, evidence = inputs(); saved = []
    args = dict(shared_experiment_schema=True, experimental_edits=True, experimental_diagnostics=True,
        experimental_nested_tables=True, experimental_intent=3)
    invoke = Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        repair_rejected(report, checks, evidence, 'Q', Mock(), json.loads, **args,
            invoke_request=invoke, checkpoint=lambda s: saved.append(deepcopy(s)))
    assert saved[-1]['pending']['request']['prepared']['nestedTablesVersion'] == 1
    assert saved[-1]['pending']['request']['outputTokens'] == 4096
    frozen = deepcopy(saved[-1]); invoke.reset_mock(); args.pop('experimental_nested_tables')
    with pytest.raises(DeepResearchError, match='原始输入'):
        repair_rejected(report, checks, evidence, 'Q', Mock(), json.loads, **args, batch_state=frozen, invoke_request=invoke)
    assert saved[-1] == frozen; invoke.assert_not_called()
