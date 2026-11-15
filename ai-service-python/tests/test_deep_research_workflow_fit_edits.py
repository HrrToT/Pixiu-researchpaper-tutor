"""Explicit local fits preserve scope and budget; no scientific acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_fit_edits as fits
from services.deep_research.contracts import digest, DeepResearchError
from services.deep_research.workflow_metadata_symbols import decode, field_feedback
from services.deep_research.workflow_units import unit_errors, META
from services.deep_research.workflow_metadata_repair import prepare
from test_deep_research_workflow_revision_sources import record as previous


def record(): return {**previous(), 'workflowFitEditsContractVersion': 1,
    'workflowMetadataEditsContractVersion': 2, 'workflowRevisionReasoningContractVersion': 0}


def example():
    path = Path(__file__).parent / 'fixtures/dr_fit_group_revision_20261115.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '24c974547dd366a1bf3862a2b4e3b35eb71fc4b546b850ffcfd94abb6c36d38b'
    wire = json.loads(path.read_text(encoding='utf8'))['wire']; aliases = {f'E{i}': f'E{i}' for i in range(1, 21)}
    feedback = {**field_feedback(wire, aliases), 'codes': unit_errors(decode(wire), aliases, node=META, version=7, metadata_rows=True)}
    scope = fits.scope_for(record(), wire, feedback)
    assert scope and feedback['codes'] == ['timeline.input.group_leak']
    return wire, aliases, feedback, scope


def patch_for(wire, scope):
    # Authored test proposal only. This mapping is never production behavior.
    targets = {'00': ['gaussian_parameters'], '01': ['gaussian_parameters', 'sh_codebook', 'sh_indices'],
               '10': ['gaussian_parameters', 'cov_codebook', 'cov_indices'],
               '11': ['gaussian_parameters', 'sh_codebook', 'sh_indices', 'cov_codebook', 'cov_indices']}
    steps = []
    for group, states in targets.items():
        step = deepcopy(wire['steps'][1]); step['groups'] = [group]; step['updates'] = states
        step['outputs'] = deepcopy(wire['steps'][1]['outputs']) if group == '11' else ['fit_' + group]
        steps.append(step)
    return {'baseDigest': scope['baseDigest'], 'readEdits': [], 'fitEdits': [{'path': '/steps/1', 'steps': steps}], 'unresolved': []}


@pytest.mark.parametrize('marker', [None, True, False, 0, 2, '1'])
def test_marker_is_strict(marker):
    w, _, f, _ = example()
    assert fits.scope_for({**record(), 'workflowFitEditsContractVersion': marker}, w, f) is None


@pytest.mark.parametrize('key', ['workflowRevisionContextContractVersion', 'workflowMetadataEditsContractVersion',
    'workflowRevisionInputContractVersion', 'workflowMetadataOutputContractVersion'])
def test_partial_profiles_cannot_change_revision_mode(key):
    w, _, f, _ = example(); assert fits.scope_for({**record(), key: 0}, w, f) is None


def test_saved_negative_is_four_updates_and_scope_contains_only_diagnosed_fit():
    w, _, f, s = example(); before = deepcopy(w)
    assert len(f['issues']) == 4 and s['fitPaths'] == ['/steps/1'] and s['readPaths'] == []
    patch = patch_for(w, s); result = fits.apply(w, patch, s)
    assert w == before and result['steps'][:1] == w['steps'][:1] and result['steps'][5:] == w['steps'][2:]
    assert {k: v for k, v in result.items() if k != 'steps'} == {k: v for k, v in w.items() if k != 'steps'}
    assert not unit_errors(decode(result), {f'E{i}': f'E{i}' for i in range(1, 21)}, node=META, version=7, metadata_rows=True)


@pytest.mark.parametrize('change', ['absolute_creation', 'absolute_disposal', 'result_consumer', 'wrong_actual', 'other_error', 'setup_update'])
def test_unsafe_dependencies_and_nonfit_diagnoses_use_full_revision(change):
    w, _, f, _ = example()
    if change == 'absolute_creation': w['components'][0]['lifecycle']['createInScope'] = 1
    if change == 'absolute_disposal': w['components'][0]['lifecycle']['disposeAfter'] = 12
    if change == 'result_consumer': w['steps'][2]['reads'].append({'result': w['steps'][1]['outputs'][0], 'selector': 'all'})
    if change == 'wrong_actual': f['issues'][0]['actual'] = 'different'
    if change == 'other_error': f['codes'].append('timeline.phase.action')
    if change == 'setup_update': w['steps'][1]['kind'] = 'setup'
    assert fits.scope_for(record(), w, f) is None


@pytest.mark.parametrize('change,code', [('missing_group', 'fit_groups'), ('overlap', 'fit_groups'),
    ('extra_group', 'fit_groups'), ('budget', 'fit_budget_scope'), ('boolean_budget', 'fit_budget_scope'),
    ('scope', 'fit_budget_scope'), ('no_update', 'fit_updates'), ('unavailable_update', 'fit_update_groups'),
    ('lost_update', 'fit_update_coverage'), ('lost_output', 'fit_outputs'), ('repeated_output', 'fit_outputs'),
    ('wrong_target', 'scope'), ('duplicate_edit', 'scope'), ('missing_edit', 'fit_count'), ('unresolved', 'unresolved')])
def test_model_cannot_remove_arms_updates_outputs_or_budgets(change, code):
    w, _, _, s = example(); p = patch_for(w, s); steps = p['fitEdits'][0]['steps']
    if change == 'missing_group': del steps[0]
    if change == 'overlap': steps[0]['groups'].append('01')
    if change == 'extra_group': steps[0]['groups'] = ['other']
    if change == 'budget': steps[0]['budget']['perExecution'] += 1
    if change == 'boolean_budget': steps[0]['budget']['perExecution'] = True
    if change == 'scope': steps[0]['scope'] = 'per_frame'
    if change == 'no_update': steps[0]['updates'] = []
    if change == 'unavailable_update': steps[0]['updates'].append('sh_codebook')
    if change == 'lost_update': steps[1]['updates'].remove('sh_codebook')
    if change == 'lost_output': steps[3]['outputs'].pop()
    if change == 'repeated_output': steps[0]['outputs'] = steps[3]['outputs']
    if change == 'wrong_target': p['fitEdits'][0]['path'] = '/steps/0'
    if change == 'duplicate_edit': p['fitEdits'].append(deepcopy(p['fitEdits'][0]))
    if change == 'missing_edit': p['fitEdits'] = []
    if change == 'unresolved': p['unresolved'] = ['need more information']
    before = deepcopy(w)
    with pytest.raises(fits.EditError) as error: fits.apply(w, p, s)
    assert error.value.code == code and w == before


def test_original_read_indices_are_applied_before_step_replacement():
    w, aliases, _, _ = example(); w['steps'][2]['reads'].append({'state': 'sh_codebook', 'selector': 'all'})
    f = {**field_feedback(w, aliases), 'codes': ['timeline.input.group_leak']}; s = fits.scope_for(record(), w, f)
    assert s['readPaths'] == ['/steps/2/reads/1']
    p = patch_for(w, s); p['readEdits'] = [{'op': 'remove', 'path': '/steps/2/reads/1'}]
    value = fits.apply(w, p, s)
    assert value['steps'][5]['reads'] == w['steps'][2]['reads'][:1]
    assert not unit_errors(decode(value), aliases, node=META, version=7, metadata_rows=True)


def test_multiple_fit_replacements_use_original_indices_and_preserve_following_steps():
    w, aliases, _, _ = example(); second = deepcopy(w['steps'][1])
    second['outputs'] = ['second_' + name for name in second['outputs']]
    w['steps'].insert(2, second)
    f = {**field_feedback(w, aliases), 'codes': ['timeline.input.group_leak']}; s = fits.scope_for(record(), w, f)
    assert s['fitPaths'] == ['/steps/1', '/steps/2']
    p = patch_for(w, s); second_edit = deepcopy(p['fitEdits'][0]); second_edit['path'] = '/steps/2'
    for step in second_edit['steps']: step['outputs'] = ['second_' + name for name in step['outputs']]
    p['fitEdits'].append(second_edit)
    value = fits.apply(w, p, s)
    assert value['steps'][1:5] == p['fitEdits'][0]['steps']
    assert value['steps'][5:9] == second_edit['steps'] and value['steps'][9:] == w['steps'][3:]
    assert not unit_errors(decode(value), aliases, node=META, version=7, metadata_rows=True)
    p['fitEdits'][1]['steps'][0]['outputs'] = p['fitEdits'][0]['steps'][0]['outputs']
    with pytest.raises(fits.EditError, match='fit_outputs'): fits.apply(w, p, s)


def test_new_fit_outputs_cannot_shadow_untouched_measurement_results():
    w, _, _, s = example(); p = patch_for(w, s)
    p['fitEdits'][0]['steps'][0]['outputs'] = [w['steps'][2]['outputs'][0]]
    with pytest.raises(fits.EditError, match='fit_outputs'): fits.apply(w, p, s)


def test_schema_accepts_authored_patch_and_internal_mode_cannot_leak_or_mix():
    from jsonschema import Draft202012Validator
    from services.deep_research.experiment_planning import request_identity
    from llm.responses_transport import payload
    w, _, _, s = example(); p = patch_for(w, s)
    Draft202012Validator.check_schema(fits.descriptor()['schema'])
    Draft202012Validator(fits.descriptor()['schema']).validate(p)
    req = request_identity(record(), fits.NODE, 'complete proposal', {fits.OPTION: True})
    wire = payload(req['messages'], req['extra'], model='fixture', temperature=0)
    assert fits.OPTION not in wire and wire['text']['format']['name'] == fits.NAME
    assert 'sourceRefs' not in wire['text']['format']['schema']['properties']
    with pytest.raises(ValueError):
        request_identity(record(), fits.NODE, 'complete', {fits.OPTION: True, '_workflow_metadata_edits': True})
    with pytest.raises(ValueError):
        request_identity(record(), 'plan_workflow_meta', 'complete', {fits.OPTION: True})


def test_legacy_full_revision_identity_cannot_be_reused_as_local_edit():
    w, aliases, _, _ = example(); source = '{}'; saved = []
    class BeforeProvider(Exception): pass
    with pytest.raises(BeforeProvider):
        prepare(previous(), source_data=source, failed=failed(w), aliases=aliases, existing=None,
                invoke=Mock(side_effect=BeforeProvider()), checkpoint=saved.append)
    no_send = Mock()
    with pytest.raises(DeepResearchError, match='身份或状态'):
        prepare(record(), source_data=source, failed=failed(w), aliases=aliases, existing=saved[-1], invoke=no_send, checkpoint=lambda _: None)
    no_send.assert_not_called()


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_http_mode_budget_and_unknown_identity_are_preserved(tmp_path, monkeypatch, scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.planning_transport import dispatch_options, overhead_bytes
    from services.deep_research.experiment_planning import request_identity
    from services.deep_research.contracts import BudgetExhaustedError, UnknownCallError, UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r = record(); r.update(runId='r', taskId='t')
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    post = Mock(side_effect=requests.ReadTimeout('unknown')) if scenario == 'unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post', post)
    client = ScopedModelClient(repo, lambda *a: True, lambda: DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')).for_run('r')
    reserve = Mock(side_effect=BudgetExhaustedError('tokens', 100001, 100000)) if scenario == 'budget' else Mock(wraps=repo.reserve_call)
    tracked = TrackedLLMInvoker(client, reserve, repo.complete_call, request_options=research_model_options,
        run_record_fn=repo.require_run, workflow_revision_context_max_input_bytes=64000)
    req = request_identity(r, fits.NODE, 'complete original inputs', {fits.OPTION: True})
    def run(): return tracked('r', fits.NODE, req['prompt'], dispatch_options(r, fits.NODE, req['extra']), use_reserve=True)
    if scenario == 'budget':
        with pytest.raises(BudgetExhaustedError): run()
        post.assert_not_called(); return
    if scenario == 'unknown':
        with pytest.raises(LLMProviderError): run()
        with pytest.raises((UnknownCallError, UnresolvedUnknownError)): run()
    else: run()
    assert post.call_count == 1 and repo.list_calls('r')[0]['argsDigest'] == digest(req)
    wire = post.call_args.kwargs['json']
    assert wire['text']['format']['name'] == fits.NAME and fits.OPTION not in wire
    assert wire['max_output_tokens'] == 6144 and post.call_args.kwargs['timeout'] == 90
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == len(req['prompt'].encode()) + 1024 + overhead_bytes(r, fits.NODE, req['extra']) + 6144


def failed(w):
    value = decode(w); response = {'content': json.dumps(w), 'finishReason': 'stop'}
    return {'status': 'invalid_response', 'request': {'prompt': 'saved negative'}, 'response': response,
        'responseDigest': digest(response), 'value': value, 'valueDigest': digest(value), 'errors': ['timeline.input.group_leak']}


def test_production_prepare_compiles_and_reopens_without_resend_or_data_changes():
    w, aliases, _, s = example(); p = patch_for(w, s); snapshots = []; source = json.dumps({'question': 'keep all four arms'})
    response = {'content': json.dumps(p), 'finishReason': 'stop'}; invoke = Mock(return_value=response)
    value = prepare(record(), source_data=source, failed=failed(w), aliases=aliases, existing=None, invoke=invoke, checkpoint=snapshots.append)
    saved = snapshots[-1]
    assert saved['status'] == 'ready' and saved['compiledWire'] == fits.apply(w, p, s)
    assert saved['request']['extra'][fits.OPTION] is True
    assert saved['request']['extra']['response_format']['name'] == fits.NAME
    no_send = Mock()
    assert prepare(record(), source_data=source, failed=failed(w), aliases=aliases, existing=saved, invoke=no_send, checkpoint=lambda _: None) == value
    no_send.assert_not_called()
    tampered = deepcopy(saved); tampered['compiledWire']['sourceRefs'] = []
    with pytest.raises(DeepResearchError, match='编译结果'):
        prepare(record(), source_data=source, failed=failed(w), aliases=aliases, existing=tampered, invoke=no_send, checkpoint=lambda _: None)
    no_send.assert_not_called()


@pytest.mark.parametrize('reason', ['length', 'unresolved', 'invalid_patch'])
def test_failure_is_preserved_and_never_triggers_a_second_full_rewrite(reason):
    w, aliases, _, s = example(); p = patch_for(w, s)
    if reason == 'unresolved': p['unresolved'] = ['not representable']
    if reason == 'invalid_patch': p['fitEdits'][0]['steps'][0]['groups'] = ['11']
    invoke = Mock(return_value={'content': json.dumps(p), 'finishReason': 'length' if reason == 'length' else 'stop'})
    snapshots = []
    with pytest.raises(DeepResearchError):
        prepare(record(), source_data='{}', failed=failed(w), aliases=aliases, existing=None, invoke=invoke, checkpoint=snapshots.append)
    saved = snapshots[-1]; assert saved['status'] == 'invalid_response' and invoke.call_count == 1
    with pytest.raises(DeepResearchError):
        prepare(record(), source_data='{}', failed=failed(w), aliases=aliases, existing=saved, invoke=invoke, checkpoint=lambda _: None)
    assert invoke.call_count == 1


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_server_owned_immutable_flag(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize(); facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Design',
            'deferStart': True, 'workflowFitEditsContractVersion': replacement}, start_async=False)
        assert r['workflowFitEditsContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda x: {**x, 'workflowFitEditsContractVersion': replacement})
        old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop('workflowFitEditsContractVersion'); repo.create_run(old)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run('old', lambda x: {**x, 'workflowFitEditsContractVersion': 1})
    finally: facade.shutdown()
