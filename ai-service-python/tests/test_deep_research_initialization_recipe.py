"""Recipes use existing fields without changing saved context or scientific gates."""
import json
from copy import deepcopy

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_initialization_recipe import MARKER, POLICY, enabled
from services.deep_research.workflow_initialization_context import project, STATE_POLICY
from services.deep_research.workflow_units import INIT, unit_prompt
from services.deep_research.planning_transport import descriptor_for, overhead_bytes
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


_legacy_record = context_tests.record


def record():
    return {**_legacy_record(), 'workflowInitializationContextContractVersion': 2, MARKER: 1}


@pytest.mark.parametrize('value', [None, False, True, 0, 2, '1'])
def test_recipe_contract_is_strictly_server_versioned(value):
    r = record(); r[MARKER] = value
    assert not enabled(r)


def test_recipe_requires_the_complete_current_initialization_profile():
    assert enabled(record())
    for key in ('workflowInitializationContextContractVersion', 'workflowPremiseAllocationContractVersion',
                'workflowInitializationRepairContractVersion'):
        r = record(); r.pop(key)
        assert not enabled(r)


def test_recipe_preserves_all_source_and_projected_context_values():
    source = {'question': 'all four arms unchanged', 'evidence': [{'alias':'E1','quote':'Exact source'}],
              'unverifiedScientificPlan': {'states': 'position, opacity, scale, rotation, DC, SH'}}
    ctx = context_tests.context(); before = deepcopy(ctx)
    args = dict(node=INIT, context=ctx, version=7, scoped_initialization_input=True,
                initialization_context_version=2)
    legacy = unit_prompt(json.dumps(source), **args)
    current = unit_prompt(json.dumps(source), **args, initialization_recipe=True)
    assert current.startswith(POLICY) and legacy.startswith(STATE_POLICY)
    assert input_value(current) == input_value(legacy) == {
        'authoritativeInput':source, 'unitContext':project(ctx)}
    assert ctx == before
    assert 'entity, fields and axis meanings' in current
    assert 'actual computation/formula' in current
    assert 'source=training_data is not a recipe' in current
    assert 'later-created states' in current and 'packing' in current
    assert len(POLICY.encode()) <= len(STATE_POLICY.encode())


@pytest.mark.parametrize('options', [
    {'initialization_recipe': 1},
    {'initialization_recipe': True, 'initialization_context_version': 1},
    {'initialization_recipe': True, 'scoped_initialization_input': False},
])
def test_invalid_prompt_mode_fails_before_generation(options):
    args = dict(node=INIT, context=context_tests.context(), version=7,
                scoped_initialization_input=True, initialization_context_version=2)
    args.update(options)
    with pytest.raises(ValueError): unit_prompt('{}', **args)


def test_no_schema_output_or_transport_budget_expansion():
    new = record(); old = deepcopy(new); old.pop(MARKER)
    for target in ('baseline', 'component'):
        assert descriptor_for(new, INIT, target) == descriptor_for(old, INIT, target)
        options = {'_workflow_init_target':target}
        assert overhead_bytes(new, INIT, options) == overhead_bytes(old, INIT, options)


def test_complete_workflow_preserved_and_reopen_does_not_resend():
    r, invoke, run = context_tests.setup()
    r.update({MARKER:1, 'workflowInitializationContextContractVersion':2})
    saved = run(); assert saved['status'] == 'ready'
    full, _, _ = context_tests.fixtures()
    assert saved['value']['workflow']['componentInitializations'] == full['componentInitializations']
    assert saved['value']['workflow']['phases'] == full['phases']
    assert saved['request']['initializationRecipeContract'] == 1
    for call in invoke.call_args_list:
        if call.args[0] == INIT: assert POLICY in call.args[1]
        else: assert 'source=training_data is not a recipe' not in call.args[1]
    count = invoke.call_count
    assert run() == saved and invoke.call_count == count


def test_existing_workflow_cannot_enable_recipe_and_reinterpret_cached_units():
    r, invoke, run = context_tests.setup()
    r['workflowInitializationContextContractVersion'] = 2
    run(); count = invoke.call_count; r[MARKER] = 1
    with pytest.raises(DeepResearchError, match='原始输入不一致'): run()
    assert invoke.call_count == count


def test_failed_initialization_repair_keeps_recipe_and_full_context_validation():
    r, invoke, run = context_tests.setup()
    r.update({MARKER:1, 'workflowInitializationContextContractVersion':2})
    calls = list(invoke.side_effect); bad = deepcopy(calls[-1])
    value = json.loads(bad['content'])
    value['initialization']['input'] = {'phaseId':'missing','outputId':'r0','selector':'all'}
    bad['content'] = json.dumps(value); calls[-1] = bad
    invoke.side_effect = calls + [bad]
    with pytest.raises(DeepResearchError): run()
    state = r['state']['executionWorkflowBlueprint']
    assert state['units']['component:1']['status'] == 'invalid_response'
    repair = state['initializationRepair']
    assert POLICY in repair['request']['prompt'] and repair['status'] == 'invalid_response'
    assert 'metadataHeader' in input_value(repair['request']['prompt'])['unitContext']


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_recipe_marker_is_server_owned_and_immutable(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design',
            'deferStart':True, MARKER:replacement}, start_async=False)
        assert r[MARKER] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda old: {**old, MARKER:replacement})
        old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop(MARKER)
        repo.create_run(old)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run('old', lambda item: {**item, MARKER:1})
    finally: facade.shutdown()


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_actual_http_capacity_and_no_unknown_or_budget_resend(tmp_path, monkeypatch, scenario):
    monkeypatch.setattr(context_tests, 'record', record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path, monkeypatch, scenario)
