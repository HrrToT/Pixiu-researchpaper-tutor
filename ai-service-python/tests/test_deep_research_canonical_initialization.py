import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_workflow import workflow_errors, workflow_text
from services.deep_research.experiment_protocol import protocol_errors, enforce_protocol_consistency
from services.deep_research.design_consistency import enforce_design_consistency
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.completion_criteria import completion_contract_digest
from services.deep_research.verification import verify_claims
from services.deep_research.graph import make_synthesize_node
from services.deep_research.repair import repair_rejected
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_creation_inputs import claim as legacy_steps
from test_deep_research_experiment_protocol import claim as legacy_controls, data as data_spec
from test_deep_research_budget_contract import budget_spec, group_spec
from test_deep_research_state_initialization import definitions


def claims():
    steps = legacy_steps()
    steps['workflowContractVersion'] = 4
    init = {'initializationMode': 'fresh', 'inputs': [],
        'creation': {'action': 'Create the model using the listed initial states.', 'parameters': []},
        'stateDefinitions': definitions()}
    steps['executionSpec']['baselineInitialization'] = deepcopy(init)
    steps['executionSpec']['componentInitializations'] = [{**deepcopy(init),
        'componentId': 'residual', 'appliesTo': ['0', '1']}]
    controls = legacy_controls()
    controls['protocolContractVersion'] = 2
    controls['executionSpec']['initialization'] = {'workflowClaimId': 'steps'}
    data = {'claimId': 'data', 'kind': 'proposal', 'designRole': 'data', 'designContractVersion': 2,
        'protocolContractVersion': 2, 'text': 'Fixture-only proposed data scope.', 'evidenceRefs': [], 'executionSpec': data_spec()}
    data['executionSpec']['replication']['mode'] = 'retrained_per_seed'
    budget = {'claimId': 'budget', 'kind': 'proposal', 'designRole': 'budget', 'designContractVersion': 2,
        'budgetContractVersion': 1, 'text': 'Fixture-only budget.', 'evidenceRefs': [],
        'executionSpec': budget_spec({'0': 100, '1': 100})}
    groups = {'claimId': 'groups', 'kind': 'proposal', 'designRole': 'groups', 'designContractVersion': 2,
        'text': 'Fixture-only groups.', 'evidenceRefs': [], 'executionSpec': group_spec(1)}
    return [data, budget, groups, controls, steps]


def test_canonical_initialization_links_valid_states_without_mutation_or_scientific_approval():
    rows = claims()
    original = deepcopy(rows)
    result = enforce_design_consistency({'accepted': rows, 'rejected': []}, protocol_required=2, workflow_required=4)
    assert result['accepted'] == rows and not result['rejected'] and rows == original
    for c in rows[-2:]:
        assert verification_claim_view(materialize_execution_claim(c)) == c
        assert not verify_claims([c], [])['accepted']
    text = workflow_text(rows[-1])
    assert '<summary>基线初始状态</summary>' in text
    assert '<summary>residual的初始状态</summary>' in text
    assert 'float32，形状4×2' in text and '标准差0.01' in text
    assert '最终评估集不得用于初始化' in text


@pytest.mark.parametrize('change', ['missing_baseline', 'baseline_self_input', 'evaluation_input',
    'missing_states', 'shape_without_values', 'absent_creation_rule', 'existing_with_creation'])
def test_incomplete_initialization_is_rejected_before_semantic_review(change):
    c = claims()[-1]
    s = c['executionSpec']
    if change == 'missing_baseline': s.pop('baselineInitialization')
    elif change in {'baseline_self_input', 'evaluation_input'}:
        s['baselineInitialization'].update(initializationMode='derive',
            inputs=[{'state': 'baseline' if change == 'baseline_self_input' else 'evaluation_data', 'selector': 'all entries'}])
    elif change == 'missing_states': s['componentInitializations'][0].pop('stateDefinitions')
    elif change == 'shape_without_values': s['componentInitializations'][0]['stateDefinitions'][0].pop('initializer')
    elif change == 'absent_creation_rule': s['baselineInitialization']['creation'] = None
    elif change == 'existing_with_creation': s['baselineMode'] = 'existing'
    check = Mock()
    result = verify_claims([c], [], check)
    assert not result['accepted'] and result['rejected'][0]['reason'] == 'incomplete_experiment_workflow'
    check.assert_not_called()


@pytest.mark.parametrize('change', ['other_steps', 'self', 'extra_checkpoint', 'old_operation', 'ambiguous_steps'])
def test_controls_cannot_name_a_second_or_unverified_initialization_source(change):
    rows = claims()
    controls, steps = rows[-2:]
    if change == 'other_steps': controls['executionSpec']['initialization']['workflowClaimId'] = 'another'
    elif change == 'self': controls['executionSpec']['initialization']['workflowClaimId'] = 'controls'
    elif change == 'extra_checkpoint': controls['executionSpec']['initialization']['checkpoint'] = 'unknown.pt'
    elif change == 'old_operation': controls['executionSpec']['initialization'] = legacy_controls()['executionSpec']['initialization']
    elif change == 'ambiguous_steps': rows.append(deepcopy(steps))
    checked = enforce_protocol_consistency({'accepted': rows, 'rejected': []}, required=2)
    assert 'controls' not in [c['claimId'] for c in checked['accepted']]


def test_loss_of_a_later_budget_dependency_also_removes_orphan_workflow_and_controls():
    rows = claims()
    rows[1]['executionSpec']['recovery']['groups'] = {'00': 100, '01': 100, '10': 100, '11': 100}
    before = deepcopy(rows)
    result = enforce_design_consistency({'accepted': rows, 'rejected': []}, protocol_required=2, workflow_required=4)
    remaining = {c['claimId'] for c in result['accepted']}
    assert not {'budget', 'steps', 'controls'} & remaining
    assert rows == before
    assert len({r['claimId'] for r in result['rejected']}) == len(result['rejected'])


def test_initialization_is_reviewed_scientifically_even_with_complete_typed_values():
    rows = claims()
    def invoke(**request):
        assert request['node'] == 'verify_repair_design_science'
        assert 'enumerate ALL states required' in request['prompt']
        assert 'ONLY initialization definition' in request['prompt']
        return {'content': json.dumps([{'claimId': 'steps', 'status': 'failed',
            'reason': 'The fixture initialization does not define the proposed Gaussian representation.'}])}
    result = BudgetedSemanticChecker(invoke, 'offline').check_revisions([rows[-1]], [], rows[:-1])
    assert result[0]['status'] == 'failed'


def test_changes_in_state_values_and_hidden_canonical_reference_invalidate_completion():
    plan = [{'obligations': [{'obligationId': 'o', 'question': 'Design.',
        'completionCriteria': [{'criterionId': 'steps', 'requirement': 'Executable.', 'responseType': 'procedure'}]}]}]
    rows = [materialize_execution_claim(c) for c in claims()[-2:]]
    original = completion_contract_digest(plan, rows)
    rows[0]['executionSpec']['initialization']['workflowClaimId'] = 'different_steps'
    assert completion_contract_digest(plan, rows) != original
    rows = [materialize_execution_claim(c) for c in claims()[-2:]]
    rows[-1]['executionSpec']['baselineInitialization']['stateDefinitions'][0]['initializer']['std'] = .02
    assert completion_contract_digest(plan, rows) != original


def test_synthesis_and_repair_cannot_downgrade_state_or_protocol_contracts():
    rows = claims()[-2:]
    record = {'question': 'Design an unexecuted experiment.', 'protocolContractVersion': 2, 'workflowContractVersion': 4,
        'state': {'outputKind': 'experiment_design', 'plan': [], 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(run, node, prompt, options, **kwargs):
        assert 'Protocol contract 2' in prompt and 'Workflow contract 4' in prompt
        assert 'stateDefinitions' in prompt
        return {'content': json.dumps({'claims': [{**c, 'protocolContractVersion': 1,
            'workflowContractVersion': 1} for c in rows]})}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    stored = record['state']['reportBody']['claims']
    assert stored[0]['protocolContractVersion'] == 2 and stored[1]['workflowContractVersion'] == 4
    response = [{**verification_claim_view(c), 'protocolContractVersion': 1, 'workflowContractVersion': 1}
                for c in stored]
    revised = repair_rejected({'claims': stored}, {'rejected': [{'claimId': c['claimId'], 'reason': 'incomplete'} for c in stored]},
        [], record['question'], Mock(return_value={'content': json.dumps(response)}), json.loads)
    assert revised[0]['protocolContractVersion'] == 2 and revised[1]['workflowContractVersion'] == 4


def test_old_three_workflow_and_one_protocol_remain_readable_without_new_state_fields():
    steps = legacy_steps()
    assert workflow_errors(steps['executionSpec'], 2) == []
    assert verification_claim_view(materialize_execution_claim(steps)) == steps
    c = legacy_controls()
    assert protocol_errors('controls', c['executionSpec'], 1) == []
    assert verification_claim_view(materialize_execution_claim(c)) == c


def test_create_cannot_opt_out_of_server_canonical_initialization_contracts(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(str(tmp_path / 'canonical.sqlite3'))
    repo.initialize()
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object())
    try:
        response, created = facade.create({'workspaceTaskId': 't', 'operationKey': 'new',
            'question': 'Design an experiment.', 'materials': [], 'workflowContractVersion': 1,
            'protocolContractVersion': 1}, start_async=False)
        saved = repo.require_run(response['runId'])
        assert created and saved['workflowContractVersion'] == 5 and saved['protocolContractVersion'] == 2
    finally:
        facade.shutdown()
