import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_workflow import (
    enforce_workflow_consistency, workflow_errors, workflow_text)
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.verification import verify_claims
from services.deep_research.graph import make_synthesize_node
from services.deep_research.repair import repair_rejected
from services.deep_research.completion_criteria import completion_contract_digest
from test_deep_research_experiment_workflow import claim as old_claim, siblings, checked


def claim():
    value = old_claim()
    value['workflowContractVersion'] = 2
    value['executionSpec']['componentInitializations'] = [{
        'componentId': 'residual', 'initializationMode': 'derive',
        'inputs': [{'state': 'baseline', 'selector': 'all trained point positions and scales'}],
        'creation': {'action': 'Create an independent residual buffer from the selected positions/scales; zero its new color weights.',
            'parameters': [{'name': 'new_color_weight', 'type': 'number', 'value': 0},
                           {'name': 'count', 'type': 'choice', 'value': 'one per selected primitive'}]},
        'appliesTo': ['0', '1']}]
    value['executionSpec']['records'].append('group_checkpoints')
    return value


def test_existing_input_creation_then_paired_copies_remains_a_proposal_not_a_factual_approval():
    c = claim()
    before = deepcopy(c)
    assert workflow_errors(c['executionSpec'], 2) == []
    assert enforce_workflow_consistency(checked(c), required=2)['accepted'][-1] == c
    result = verify_claims([c], [], lambda *_: [{'claimId': 'steps', 'status': 'failed',
        'reason': 'The selected state does not define a scientifically valid residual component.'}])
    assert result['accepted'] == [] and result['rejected'][0]['reason'] == 'semantic_unresolved'
    assert c == before


@pytest.mark.parametrize('change', ['missing_inputs', 'absent_component', 'self_reference',
    'forward_reference', 'fresh_with_input', 'derive_without_input', 'empty_selector',
    'duplicate_input', 'reserved_identity', 'missing_checkpoint', 'boolean_version', 'unknown_version'])
def test_creation_cannot_read_a_state_that_does_not_exist_or_drop_required_artifacts(change):
    c = claim()
    spec = c['executionSpec']
    component = spec['componentInitializations'][0]
    if change == 'missing_inputs': component.pop('inputs')
    elif change == 'absent_component': component['inputs'][0]['state'] = 'nonexistent_enhancement'
    elif change == 'self_reference': component['inputs'][0]['state'] = 'residual'
    elif change == 'forward_reference':
        later = deepcopy(component)
        later['componentId'] = 'later'
        spec['componentInitializations'].append(later)
        component['inputs'][0]['state'] = 'later'
    elif change == 'fresh_with_input': component['initializationMode'] = 'fresh'
    elif change == 'derive_without_input': component['inputs'] = []
    elif change == 'empty_selector': component['inputs'][0]['selector'] = ' '
    elif change == 'duplicate_input': component['inputs'] *= 2
    elif change == 'reserved_identity': component['componentId'] = 'baseline'
    elif change == 'missing_checkpoint': spec['records'].remove('group_checkpoints')
    elif change == 'boolean_version': c['workflowContractVersion'] = True
    elif change == 'unknown_version': c['workflowContractVersion'] = 999
    semantic = Mock()
    assert not verify_claims([c], [], semantic)['accepted']
    semantic.assert_not_called()


def test_fresh_component_then_explicit_dependent_component_are_created_in_available_order():
    c = claim()
    first = c['executionSpec']['componentInitializations'][0]
    first['initializationMode'] = 'fresh'
    first['inputs'] = []
    first['creation'] = {'action': 'Create a one-dimensional zero vector.',
        'parameters': [{'name': 'length', 'type': 'number', 'value': 4},
                       {'name': 'initial_value', 'type': 'number', 'value': 0},
                       {'name': 'state_layout', 'type': 'choice', 'value': 'one vector of length four; every entry starts at zero'}]}
    second = deepcopy(first)
    second.update(componentId='derived', initializationMode='derive',
                  inputs=[{'state': 'residual', 'selector': 'all four entries'}])
    second['creation']['action'] = 'Copy selected entries into a separate new vector.'
    c['executionSpec']['componentInitializations'].append(second)
    assert workflow_errors(c['executionSpec'], 2) == []
    second['inputs'][0]['state'] = 'evaluation_data'
    assert 'workflow.creation.unavailable_input' in workflow_errors(c['executionSpec'], 2)


def test_readable_workflow_preserves_all_choices_and_final_evaluation_isolation_without_raw_json():
    c = claim()
    c['executionSpec']['checkpointSelection'] = {'mode': 'validation_split',
        'split': {'mode': 'seeded_fraction', 'evaluationFraction': .2, 'seed': 7},
        'rule': {'action': 'Choose the lowest validation loss checkpoint.',
            'parameters': [{'name': 'tie_rule', 'type': 'choice', 'value': 'earliest step'}]}}
    text = workflow_text(c)
    for expected in ['已有基线', 'all trained point positions and scales', 'new_color_weight：0',
                     'one per selected primitive', '组 0、1', '验证比例20%', '种子7',
                     'earliest step', '各组最终检查点', '内层拟合与验证部分必须都非空',
                     '最终评估集不得用于初始化、调参、早停或检查点选择']:
        assert expected in text
    assert '{' not in text and '"parameters"' not in text
    rendered = materialize_execution_claim(c)
    assert rendered['executionSpec'] == c['executionSpec']
    assert verification_claim_view(rendered) == c
    assert materialize_execution_claim(rendered) == rendered


def test_version_two_is_server_assigned_and_cannot_be_downgraded_in_synthesis_or_repair():
    c = claim()
    c['workflowContractVersion'] = 1
    record = {'question': 'Design an experiment.', 'workflowContractVersion': 2,
        'state': {'outputKind': 'experiment_design', 'plan': [], 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(run, node, prompt, options, **kwargs):
        assert 'Workflow contract 2' in prompt and 'initializationMode' in prompt
        return {'content': json.dumps({'claims': [c], 'workflowContractVersion': 1})}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    stored = record['state']['reportBody']['claims'][0]
    assert stored['workflowContractVersion'] == 2
    revised = {**stored, 'workflowContractVersion': 1, 'text': 'Revised planned procedure.'}
    repair = Mock(return_value={'content': json.dumps([revised])})
    result = repair_rejected({'claims': [stored]}, {'rejected': [{'claimId': 'steps', 'reason': 'incomplete'}]},
        [], 'Specify creation.', repair, json.loads)
    assert result[0]['workflowContractVersion'] == 2
    assert 'Workflow contract 2' in repair.call_args.args[0]
    assert not any(c['claimId'] == 'steps' for c in enforce_workflow_consistency(checked(old_claim()), required=2)['accepted'])


def test_completion_verdict_is_invalidated_when_an_input_selector_changes_without_changing_prose():
    plan = [{'obligations': [{'obligationId': 'o', 'question': 'Design.',
        'completionCriteria': [{'criterionId': 'steps', 'requirement': 'Executable steps.', 'responseType': 'procedure'}]}]}]
    c = claim()
    before = completion_contract_digest(plan, [c])
    c['executionSpec']['componentInitializations'][0]['inputs'][0]['selector'] = 'only the largest primitive'
    assert before != completion_contract_digest(plan, [c])


def test_legacy_workflow_keeps_original_schema_and_exact_generated_suffix():
    c = old_claim()
    assert workflow_errors(c['executionSpec']) == []
    text = workflow_text(c)
    assert '；参数=[{"name": "initial_weight", "type": "number", "value": 0}]' in text
    assert text.endswith('6. 保存基线身份、划分与种子清单、组件初态、各组配置及恢复预算、评估输出和原始测量。')
    assert verification_claim_view(materialize_execution_claim(c)) == c
