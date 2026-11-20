import json
from unittest.mock import Mock

from services.deep_research.verification import verify_claims
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_creation_inputs import claim as workflow_claim
from test_deep_research_experiment_protocol import claim as control_claim
from services.deep_research.experiment_workflow import workflow_errors, workflow_text, stamp_workflow_contract
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view


def test_fresh_initialization_cannot_use_only_a_seed_and_one_opacity_value():
    c = workflow_claim()
    c['workflowContractVersion'] = 3
    component = c['executionSpec']['componentInitializations'][0]
    component.update(initializationMode='fresh', inputs=[])
    component['creation'] = {'action': 'Randomly initialize the new Gaussian layer.',
        'parameters': [{'name': 'seed', 'type': 'number', 'value': 42},
                       {'name': 'opacity', 'type': 'number', 'value': .5}]}
    check = Mock()
    result = verify_claims([c], [], check)
    assert result['rejected'][0]['reason'] == 'incomplete_experiment_workflow'
    assert 'fresh_layout_required' in result['rejected'][0]['detail']
    check.assert_not_called()


def test_layout_is_not_a_scientific_approval_and_initialization_is_reviewed_as_science():
    c = control_claim()
    c['executionSpec']['rendering']['action'] = 'Use a general-purpose framework.'
    calls = []
    def invoke(**request):
        calls.append(request)
        assert request['node'] == 'verify_design_science'
        assert 'EACH has a defined count/shape' in request['prompt']
        assert 'actual compatible renderer' in request['prompt']
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'failed',
            'reason': 'The framework name does not define a compatible rendering operation.'}])}
    result = verify_claims([c], [], BudgetedSemanticChecker(invoke, 'r'))
    assert len(calls) == 1 and not result['accepted']
    assert result['rejected'][0]['reason'] == 'semantic_unresolved'


def test_versioned_workflow_creation_is_a_scientific_target_too():
    c = workflow_claim()
    def invoke(**request):
        assert request['node'] == 'verify_design_science'
        assert 'initialization/rendering targets' in request['prompt']
        return {'content': json.dumps([{'claimId': c['claimId'], 'status': 'failed',
            'reason': 'The proposed transformation is not compatible with its input representation.'}])}
    assert not verify_claims([c], [], BudgetedSemanticChecker(invoke, 'r'))['accepted']


def test_complete_fresh_layout_is_preserved_but_older_version_two_is_not_reinterpreted():
    c = workflow_claim()
    component = c['executionSpec']['componentInitializations'][0]
    component.update(initializationMode='fresh', inputs=[])
    component['creation'] = {'action': 'Create a four-entry vector initialized to zero.',
        'parameters': [{'name': 'state_layout', 'type': 'choice', 'value': 'one vector with shape [4]; all entries initialized to zero'},
                       {'name': 'initial_value', 'type': 'number', 'value': 0}]}
    c['workflowContractVersion'] = 3
    assert workflow_errors(c['executionSpec'], 3) == []
    rendered = materialize_execution_claim(c)
    assert '新组件状态与初值' in rendered['text'] and '[4]' in rendered['text']
    assert verification_claim_view(rendered) == c
    c['workflowContractVersion'] = 2
    component['creation']['parameters'].pop(0)
    assert workflow_errors(c['executionSpec'], 2) == []
    assert 'fresh_layout_required' in ','.join(workflow_errors(c['executionSpec'], 3))
    assert verification_claim_view(materialize_execution_claim(c)) == c


def test_server_version_three_overrides_model_downgrade_without_altering_configurations():
    c = workflow_claim()
    c['workflowContractVersion'] = 1
    report = {'claims': [c], 'workflowContractVersion': 1}
    stamped = stamp_workflow_contract(report, enabled=3)
    assert stamped['workflowContractVersion'] == stamped['claims'][0]['workflowContractVersion'] == 3
    assert stamped['claims'][0]['executionSpec'] == c['executionSpec']
    assert report['workflowContractVersion'] == c['workflowContractVersion'] == 1
