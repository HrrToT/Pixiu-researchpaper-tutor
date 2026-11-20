"""Disjoint unconsumed fit labels follow the existing decoder, v1 frozen."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_fit_edits as fits
from services.deep_research.workflow_metadata_repair import prepare
from services.deep_research.workflow_metadata_symbols import decode
from services.deep_research.workflow_units import unit_errors, META
from services.deep_research.contracts import DeepResearchError
import test_deep_research_workflow_fit_edits as previous


def record(): return {**previous.record(), 'workflowFitEditsContractVersion': 2}


def example():
    w, aliases, feedback, _ = previous.example(); scope = fits.scope_for(record(), w, feedback)
    patch = previous.patch_for(w, scope)
    for step in patch['fitEdits'][0]['steps']: step['outputs'] = deepcopy(step['updates'])
    return w, aliases, feedback, scope, patch


def test_disjoint_group_state_labels_compile_without_renaming_or_new_defaults():
    w, aliases, _, scope, patch = example(); original = deepcopy(w)
    result = fits.apply(w, patch, scope)
    assert result['steps'][1:5] == patch['fitEdits'][0]['steps'] and w == original
    assert result['sourceRefs'] == w['sourceRefs'] and result['components'] == w['components']
    assert not unit_errors(decode(result), aliases, node=META, version=7, metadata_rows=True)
    assert [s['outputs'] for s in result['steps'][1:5]] == [s['updates'] for s in patch['fitEdits'][0]['steps']]


@pytest.mark.parametrize('kind', ['same_step', 'result_consumer', 'other_step_collision', 'overlapping_groups'])
def test_same_group_collisions_and_ambiguous_consumers_still_fail(kind):
    w, _, _, scope, patch = example(); steps = patch['fitEdits'][0]['steps']
    if kind == 'same_step': steps[0]['outputs'].append(steps[0]['outputs'][0])
    if kind == 'result_consumer': steps[1]['reads'].append({'result': 'gaussian_parameters', 'selector': 'all'})
    if kind == 'other_step_collision': steps[0]['outputs'].append(w['steps'][2]['outputs'][0])
    if kind == 'overlapping_groups': steps[0]['groups'].append('01')
    before = deepcopy(w)
    with pytest.raises(fits.EditError): fits.apply(w, patch, scope)
    assert w == before


def test_same_label_in_same_group_across_separate_replacements_is_rejected():
    w, aliases, _, _, _ = example(); second = deepcopy(w['steps'][1]); second['outputs'] = ['second_' + x for x in second['outputs']]
    w['steps'].insert(2, second)
    from services.deep_research.workflow_metadata_symbols import field_feedback
    scope = fits.scope_for(record(), w, {**field_feedback(w, aliases), 'codes': ['timeline.input.group_leak']})
    p = previous.patch_for(w, scope); other = deepcopy(p['fitEdits'][0]); other['path'] = '/steps/2'
    for step in other['steps']: step['outputs'] = ['second_' + x for x in step['outputs']]
    other['steps'][0]['outputs'].append('fit_00'); p['fitEdits'].append(other)
    with pytest.raises(fits.EditError, match='fit_outputs'): fits.apply(w, p, scope)


def test_v1_duplicate_label_failure_is_not_reclassified_and_cannot_upgrade():
    w, aliases, _, scope, patch = example(); old = previous.record(); snapshots = []
    response = {'content': json.dumps(patch), 'finishReason': 'stop'}; invoke = Mock(return_value=response)
    with pytest.raises(DeepResearchError):
        prepare(old, source_data='{}', failed=previous.failed(w), aliases=aliases, existing=None, invoke=invoke, checkpoint=snapshots.append)
    saved = snapshots[-1]; assert saved['errors'] == ['unit.metadata_edit.fit_outputs']
    no_send = Mock()
    with pytest.raises(DeepResearchError):
        prepare(old, source_data='{}', failed=previous.failed(w), aliases=aliases, existing=saved, invoke=no_send, checkpoint=lambda _: None)
    with pytest.raises(DeepResearchError, match='身份或状态'):
        prepare(record(), source_data='{}', failed=previous.failed(w), aliases=aliases, existing=saved, invoke=no_send, checkpoint=lambda _: None)
    no_send.assert_not_called()


def test_v2_prepare_preserves_raw_and_compiled_values_and_reopens_without_resend():
    w, aliases, _, scope, patch = example(); snapshots = []
    response = {'content': json.dumps(patch), 'finishReason': 'stop'}
    result = prepare(record(), source_data='{}', failed=previous.failed(w), aliases=aliases, existing=None,
                     invoke=Mock(return_value=response), checkpoint=snapshots.append)
    saved = snapshots[-1]; assert saved['status'] == 'ready' and saved['response'] == response
    assert saved['request']['extra']['response_format']['name'] == 'metadata_explicit_fit_edits_v2'
    assert saved['compiledWire'] == fits.apply(w, patch, scope)
    no_send = Mock()
    assert prepare(record(), source_data='{}', failed=previous.failed(w), aliases=aliases,
                   existing=saved, invoke=no_send, checkpoint=lambda _: None) == result
    no_send.assert_not_called()


def test_feedback_is_losslessly_shared_without_removing_original_premises(monkeypatch):
    from services.deep_research import workflow_metadata_input
    w, _, feedback, scope, _ = example(); source = {'question': 'all four arms', 'evidence': [{'quote': 'complete'}]}
    real = workflow_metadata_input.input_text; captured = []
    def capture(value): captured.append(deepcopy(value)); return real(value)
    monkeypatch.setattr(workflow_metadata_input, 'input_text', capture)
    text = fits.prompt_for(json.dumps(source), w, feedback, scope)
    assert captured == [{'authoritativeInput': source, 'originalMetadata': w, 'fieldFeedback': feedback}]
    assert 'groupLeakIndex' in text and 'Unconsumed output labels may recur in disjoint groups' in text
    assert '/steps/1/updates/1' in text


def test_v1_prompt_and_descriptor_still_use_original_shape():
    w, _, feedback, old_scope = previous.example()
    text = fits.prompt_for('{}', w, feedback, old_scope)
    assert 'groupLeakIndex' not in text and 'output name once across replacements' in text
    assert fits.descriptor()['name'] == fits.NAME
    assert fits.descriptor(2)['schema'] == fits.descriptor(1)['schema']


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_v2_actual_http_ledger_and_budget_guards(tmp_path, monkeypatch, scenario):
    monkeypatch.setattr(previous, 'record', record_for_http)
    previous.test_http_mode_budget_and_unknown_identity_are_preserved(tmp_path, monkeypatch, scenario)


_legacy_record = previous.record
def record_for_http(): return {**_legacy_record(), 'workflowFitEditsContractVersion': 2}
