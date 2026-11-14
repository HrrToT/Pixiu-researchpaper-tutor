from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.state_initialization import state_definition_errors, state_definition_issues, STATE_EXPECTATIONS
from services.deep_research.experiment_diagnostics import feedback
from services.deep_research.experiment_edits import restore_columns
from services.deep_research.repair import _prepare_repair, repair_rejected, _parse_repair_response
from services.deep_research.contracts import DeepResearchError, BudgetExhaustedError
from services.deep_research.verification import verify_claims
from test_deep_research_shared_experiment_repair import inputs
from test_deep_research_state_initialization import definitions


def prepare(report=None, checks=None, evidence=None, **kw):
    r, c, e = inputs()
    return _prepare_repair(report or r, checks or c, evidence or e, 'Compare a whole stage prospectively.',
        shared_experiment_schema=True, experimental_edits=True, experimental_diagnostics=True,
        experimental_intent=3, **kw)


@pytest.mark.parametrize('dimension', [0, -1, True, 'N', {'inputIndex': 0, 'axis': 0},
    {'inputIndex': True, 'axis': 1}, {'inputIndex': 0, 'axis': -1}])
def test_shape_error_points_to_actual_state_and_dimension_without_choosing_a_value(dimension):
    states = definitions(); states[1]['shape'] = [2, dimension]
    before = deepcopy(states)
    issues = state_definition_issues(states, [], path='/executionSpec/baselineInitialization/stateDefinitions')
    assert {'path': '/executionSpec/baselineInitialization/stateDefinitions/1/shape/1', 'code': 'states.shape'} in issues
    assert state_definition_errors(states, []) == list(dict.fromkeys(i['code'] for i in issues))
    assert states == before and 'positive integer' in STATE_EXPECTATIONS['states.shape']


@pytest.mark.parametrize('change,code,suffix', [
    ('shape_type', 'states.shape', '/shape'), ('mode', 'states.initializer_mode', '/initializer/mode'),
    ('seed', 'states.seed', '/initializer/seed'), ('rng', 'states.rng', '/initializer/rng'),
    ('std', 'states.distribution_parameters', '/initializer'),
    ('literal', 'states.constant_shape', '/initializer/value'),
    ('definition', 'states.definition', '')])
def test_precise_initializer_constraints_share_the_actual_validator(change, code, suffix):
    state = {'name': 'weights', 'dtype': 'float32', 'shape': [2, 3],
        'initializer': {'mode': 'normal', 'mean': 0, 'std': .01, 'rng': 'chosen_rng', 'seed': {'mode': 'data_seed'}}}
    if change == 'shape_type': state['shape'] = '2x3'
    elif change == 'mode': state['initializer']['mode'] = 'unknown'
    elif change == 'seed': state['initializer']['seed'] = {'mode': 'fixed', 'value': True}
    elif change == 'rng': state['initializer']['rng'] = ''
    elif change == 'std': state['initializer']['std'] = 0
    elif change == 'literal': state['initializer'] = {'mode': 'constant', 'value': [[1, 2]]}
    elif change == 'definition': state['extra'] = 0
    issues = state_definition_issues([state], [])
    assert {'path': '/stateDefinitions/0' + suffix, 'code': code} in issues
    assert code in state_definition_errors([state], []) and code in STATE_EXPECTATIONS


def test_multiple_states_keep_distinct_locations_and_legacy_codes_stay_deduplicated():
    states = definitions()
    for state in states: state['shape'] = [0]
    issues = state_definition_issues(states, [])
    assert len([i for i in issues if i['code'] == 'states.shape']) == len(states)
    assert state_definition_errors(states, []).count('states.shape') == 1
    duplicate = [deepcopy(states[0]), deepcopy(states[0])]
    assert {'path': '/stateDefinitions/1', 'code': 'states.definition'} in state_definition_issues(duplicate, [])


def test_feedback_identifies_realistic_zero_collection_extra_reference_and_budget_conflicts():
    report, checks, evidence = inputs(); before = deepcopy((report, checks, evidence))
    by_role = {c['designRole']: c for c in report['claims']}
    steps = by_role['steps']['executionSpec']; steps['baselineMode'] = 'existing'; steps['baselineInitialization'] = None
    steps['componentInitializations'][0]['stateDefinitions'][0]['shape'] = [0, 59]
    by_role['controls']['executionSpec']['initialization']['baselineModel'] = {'source': 'unverified'}
    by_role['groups']['executionSpec'] = {'groups': ['0', '1']}
    by_role['budget']['executionSpec']['recovery']['groups']['0'] = 0
    changed = deepcopy(report)
    p = prepare(report, checks, evidence); f = p['schemaFeedback']
    assert ['/executionSpec/componentInitializations/0/stateDefinitions/0/shape/0', 'states.shape'] in f['targets']['steps']
    assert ['/executionSpec/baselineMode', 'workflow.baseline_mode_conflict'] in f['targets']['steps']
    assert f['targets']['controls'] == [['/executionSpec/initialization', 'controls.initialization']]
    assert f['targets']['groups'] == [['/executionSpec', 'groups.fields']]
    assert f['targets']['budget'] == [['/executionSpec/recovery', 'budget.matched']]
    assert 'choose according to' in f['rules']['budget.matched'].lower()
    assert 'no checkpoint/state/extra keys' in f['rules']['controls.initialization']
    assert p['diagnosticVersion'] == 1 and report == changed
    assert (checks, evidence) == before[1:]
    assert 'NOT scientific corrections' in p['prompt']


def test_valid_syntax_does_not_suppress_semantic_checks_or_claim_scientific_approval():
    report, checks, evidence = inputs()
    f = feedback(report['claims'])
    assert not f['targets'] and not f['rules']
    p = prepare(report, checks, evidence)
    patch = [{'claimId': 'steps', 'edits': [{'op': 'replace', 'path': '/text', 'value': 'Revised unexecuted steps.'}]}]
    revised = _parse_repair_response(p, {'content': json.dumps(patch)}, json.loads, strict_response=True)
    verifier = Mock(return_value=[{'claimId': 'steps', 'status': 'failed', 'reason': 'Actual state incompatibility.'}])
    result = verify_claims(revised, evidence, verifier)
    assert not result['accepted'] and verifier.called


def test_feedback_and_bounded_edits_preserve_all_original_claims_sources_and_checks():
    report, checks, evidence = inputs(); p = prepare()
    decode = lambda label: json.JSONDecoder().raw_decode(p['prompt'].split(label, 1)[1].lstrip())[0]
    originals = restore_columns(decode('Writable original claims:'))
    for original, target in zip(report['claims'], originals):
        assert target.get('executionSpec') == original.get('executionSpec')
        assert target['text'] == original['text'] and target.get('conditions', {}) == original.get('conditions', {})
    assert restore_columns(decode('ALL rejection checks:'))[0]['additionalChecks']
    assert restore_columns(decode('Exact original evidence/context/table data (lossless column table):'))[0]['quote'] == evidence[0]['quote']
    size = len(p['prompt'].encode())
    assert prepare(max_prompt_bytes=size)['prompt'] == p['prompt']
    with pytest.raises(BudgetExhaustedError): prepare(max_prompt_bytes=size - 1)


def test_pending_diagnostics_identity_is_frozen_and_old_edit_resume_cannot_change_it():
    report, checks, evidence = inputs(); saved = []
    args = dict(shared_experiment_schema=True, experimental_edits=True, experimental_diagnostics=True, experimental_intent=3)
    invoke = Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        repair_rejected(report, checks, evidence, 'Q', Mock(), json.loads, **args,
            invoke_request=invoke, checkpoint=lambda s: saved.append(deepcopy(s)))
    pending = saved[-1]['pending']['request']
    assert pending['outputTokens'] == 4096 and pending['prepared']['diagnosticVersion'] == 1
    assert pending['prepared']['schemaFeedback'] == feedback(report['claims'])
    frozen = deepcopy(saved[-1]); invoke.reset_mock()
    with pytest.raises(DeepResearchError, match='原始输入'):
        repair_rejected(report, checks, evidence, 'Q', Mock(), json.loads,
            shared_experiment_schema=True, experimental_edits=True, experimental_intent=3, batch_state=frozen, invoke_request=invoke)
    invoke.assert_not_called(); assert saved[-1] == frozen


def test_readonly_or_ambiguous_workflow_reference_is_not_inferred_or_accepted():
    report, _, _ = inputs(); controls = next(c for c in report['claims'] if c['designRole'] == 'controls')
    steps = next(c for c in report['claims'] if c['designRole'] == 'steps')
    result = feedback([controls], [steps, deepcopy(steps)])
    assert result['targets']['controls'] == [['/executionSpec/initialization/workflowClaimId', 'controls.workflow_link']]
    assert not feedback([controls], [steps])['targets']


def test_diagnostics_cannot_be_enabled_without_edit_format():
    report, checks, evidence = inputs()
    with pytest.raises(ValueError):
        _prepare_repair(report, checks, evidence, 'Q', experimental_diagnostics=True)
    with pytest.raises(ValueError):
        repair_rejected(report, checks, evidence, 'Q', Mock(), json.loads, experimental_diagnostics=True)


def test_malformed_dependency_values_remain_rejected_without_crashing_feedback():
    report, _, _ = inputs()
    steps = next(c for c in report['claims'] if c['designRole'] == 'steps')
    steps['executionSpec']['refs']['budget'] = []
    before = deepcopy(report)
    assert feedback(report['claims']) == {'rules': {}, 'targets': {}}
    assert report == before  # Original workflow.refs rejection is still retained.


@pytest.mark.parametrize('version', [1, 2, 3])
def test_supported_repair_versions_keep_server_grammar_gate(version):
    from services.deep_research.experiment_repair import enabled
    value = {'experimentRepairContractVersion': version, 'protocolContractVersion': 2,
        'workflowContractVersion': 4, 'budgetContractVersion': 1, 'hypothesisContractVersion': 1,
        'state': {'outputKind': 'experiment_design'}}
    assert enabled(value)
    value['workflowContractVersion'] = 3
    assert not enabled(value)
