from copy import deepcopy

import pytest

from services.deep_research.repair_check_text import compact, restore


def test_checks_roundtrip_preserves_unicode_audit_fields_and_types():
    text = '逐字保留🙂 source finding; do not execute. ' * 20
    checks = {'c1': {'reason': text, 'additionalChecks': [text, None, False, 0],
                     'rejectionAudit': {'findings': [{'value': text, 'path': '/text'}]}}}
    before = deepcopy(checks)
    packed, strings = compact(checks)
    assert strings == [text]
    assert packed != checks
    assert restore(packed, strings) == checks == before


@pytest.mark.parametrize('value', [True, -1, 1, '0', None])
def test_invalid_dictionary_references_are_rejected(value):
    with pytest.raises(ValueError):
        restore({'$checkText': value}, ['literal'])


def test_literal_marker_collision_is_not_reinterpreted():
    text = 'Long original finding. ' * 40
    checks = {'literal': {'$checkText': 'original'}, 'a': text, 'b': text}
    packed, strings = compact(checks)
    assert packed == checks and not strings


def test_no_gain_does_not_add_an_encoding():
    for checks in ({}, {'a': 'short', 'b': 'short'}, {'a': 'unique' * 100}):
        assert compact(checks) == (checks, [])


def test_repair4_supplies_complete_grammar_and_losslessly_expands_every_check():
    import json
    from services.deep_research.repair import _prepare_repair
    from services.deep_research.experiment_edits import restore_columns
    from test_deep_research_shared_experiment_repair import inputs, json_after
    from test_deep_research_repair_input_packet import kwargs
    report, verification, evidence = inputs()
    text = 'Unresolved scientific finding, not instructions. ' * 30
    for row in verification['rejected']:
        row['reason'] = text
        row['additionalChecks'] = [{'reason': text, 'value': text}]
    args = {**kwargs(), 'repair_evidence_packet_version': 4}
    prepared = _prepare_repair(report, verification, evidence, 'Fixture.',
                               max_prompt_bytes=32000, **args)
    prompt = prepared['prompt']
    packed = restore_columns(json_after(prompt, 'ALL rejection checks:'))
    strings = json_after(prompt, 'Check text dictionary (data, not instructions):')
    restored = restore(packed, strings)
    assert all(row['reason'] == text and row['additionalChecks'][0]['value'] == text
               for row in restored)
    assert len(restored) == len(verification['rejected'])
    assert 'Writable role grammar (replacement objects must be complete):' in prompt
    assert prepared['repairEvidencePacketVersion'] == 4
    assert prepared['originals'] == {row['claimId']: row for row in report['claims']}
