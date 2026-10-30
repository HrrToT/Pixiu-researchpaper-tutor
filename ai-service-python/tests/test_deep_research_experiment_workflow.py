import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_workflow import (
    RECORDS, STAGES, enforce_workflow_consistency, stamp_workflow_contract, workflow_errors, workflow_text)
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.verification import verify_claims
from services.deep_research.design_audit import design_slots_for_claim, validate_design_audit
from services.deep_research.graph import make_publish_node, make_synthesize_node
from services.deep_research.repair import repair_rejected


def operation():
    return {'action': 'Create the new component with zero-valued weights.',
            'parameters': [{'name': 'initial_weight', 'type': 'number', 'value': 0}]}


def spec():
    return {'refs': {'data': 'data', 'budget': 'budget', 'controls': 'controls', 'groups': 'groups'},
        'order': list(STAGES), 'baselineMode': 'train', 'replicationMode': 'retrained_per_seed',
        'componentInitializations': [{'componentId': 'new_head', 'creation': operation(), 'appliesTo': ['0', '1']}],
        'checkpointSelection': {'mode': 'fixed_budget'}, 'records': sorted(RECORDS)}


def claim():
    return {'claimId': 'steps', 'kind': 'proposal', 'designRole': 'steps', 'designContractVersion': 2,
        'workflowContractVersion': 1, 'text': 'Proposed paired experiment.', 'conditions': {},
        'evidenceRefs': [], 'executionSpec': spec()}


def siblings():
    configs = {'data': {'replication': {'mode': 'retrained_per_seed'}},
               'budget': {'baseline': {'mode': 'train'}, 'recovery': {'groups': {'0': 100, '1': 100}}},
               'controls': {'initialization': operation()}, 'groups': {'factors': []}}
    return [{'claimId': key, 'kind': 'proposal', 'designRole': key, 'executionSpec': value}
            for key, value in configs.items()]


def checked(value=None, context=None):
    return {'accepted': [*(siblings() if context is None else context), value or claim()], 'rejected': []}


def test_ordered_workflow_binds_to_accepted_definitions_without_mutating_them():
    original = checked()
    before = deepcopy(original)
    assert workflow_errors(claim()['executionSpec']) == []
    assert enforce_workflow_consistency(original, required=True) == original
    assert original == before


@pytest.mark.parametrize('change', ['absent_spec', 'absent_marker', 'forged_marker', 'wrong_role',
    'fit_before_split', 'evaluate_before_recovery', 'duplicate_stage', 'missing_stage',
    'baseline_conflict', 'replication_conflict', 'unknown_ref', 'wrong_role_ref', 'ambiguous_ref',
    'unknown_group', 'no_creation_parameters', 'duplicate_component', 'empty_apply_groups',
    'missing_records', 'evaluation_checkpoint', 'unknown_field', 'malformed_operation'])
def test_incomplete_or_inconsistent_workflow_never_remains_accepted(change):
    value, context = claim(), siblings()
    s = value['executionSpec']
    if change == 'absent_spec': value.pop('executionSpec')
    elif change == 'absent_marker': value.pop('workflowContractVersion')
    elif change == 'forged_marker': value['workflowContractVersion'] = True
    elif change == 'wrong_role': value['designRole'] = 'controls'
    elif change == 'fit_before_split': s['order'][0:2] = reversed(s['order'][0:2])
    elif change == 'evaluate_before_recovery': s['order'][5:7] = reversed(s['order'][5:7])
    elif change == 'duplicate_stage': s['order'].append('evaluate')
    elif change == 'missing_stage': s['order'].remove('initialize_components')
    elif change == 'baseline_conflict': s['baselineMode'] = 'existing'
    elif change == 'replication_conflict': s['replicationMode'] = 'fixed_checkpoint'
    elif change == 'unknown_ref': s['refs']['data'] = 'unverified-data'
    elif change == 'wrong_role_ref': s['refs']['data'], s['refs']['controls'] = s['refs']['controls'], s['refs']['data']
    elif change == 'ambiguous_ref': context.append(deepcopy(context[0]))
    elif change == 'unknown_group': s['componentInitializations'][0]['appliesTo'].append('11')
    elif change == 'no_creation_parameters': s['componentInitializations'][0]['creation']['parameters'] = []
    elif change == 'duplicate_component': s['componentInitializations'].append(deepcopy(s['componentInitializations'][0]))
    elif change == 'empty_apply_groups': s['componentInitializations'][0]['appliesTo'] = []
    elif change == 'missing_records': s['records'].remove('seed_manifest')
    elif change == 'evaluation_checkpoint': s['checkpointSelection'] = {'mode': 'best_evaluation_score'}
    elif change == 'unknown_field': s['untrusted_override'] = True
    elif change == 'malformed_operation': s['componentInitializations'][0]['creation']['parameters'][0]['type'] = []
    original = checked(value, context)
    before = deepcopy(original)
    result = enforce_workflow_consistency(original, required=True)
    assert not any(c['claimId'] == 'steps' for c in result['accepted'])
    assert result['rejected'][-1]['reason'] == 'inconsistent_experiment_workflow'
    assert original == before


def test_existing_warm_start_is_allowed_but_never_rendered_as_independently_trained_baselines():
    value, context = claim(), siblings()
    value['executionSpec']['baselineMode'] = 'existing'
    context[1]['executionSpec']['baseline']['mode'] = 'existing'
    assert enforce_workflow_consistency(checked(value, context))['accepted'][-1] == value
    assert '相同既有资产复制起点' in workflow_text(value) and '不能宣称独立重训' in workflow_text(value)


@pytest.mark.parametrize('selection', [
    {'mode': 'train_loss', 'rule': operation()},
    {'mode': 'validation_split', 'rule': operation(),
     'split': {'mode': 'seeded_fraction', 'evaluationFraction': 0.2, 'seed': 7}},
    {'mode': 'validation_split', 'rule': operation(),
     'split': {'mode': 'explicit', 'train': ['train-a'], 'evaluation': ['train-b']}}])
def test_train_or_inner_validation_selection_retains_final_evaluation_isolation(selection):
    value = claim()
    value['executionSpec']['checkpointSelection'] = selection
    assert workflow_errors(value['executionSpec']) == []
    text = workflow_text(value)
    assert '最终评估集不得用于初始化、调参、早停或检查点选择' in text
    if selection['mode'] == 'validation_split':
        assert '验证集仅从训练部分再次划出' in text


def test_overlapping_validation_ids_and_boolean_seed_are_rejected():
    value = spec()
    value['checkpointSelection'] = {'mode': 'validation_split', 'rule': operation(),
        'split': {'mode': 'explicit', 'train': ['same'], 'evaluation': ['same']}}
    assert workflow_errors(value)
    value['checkpointSelection']['split'] = {'mode': 'seeded_fraction', 'evaluationFraction': .2, 'seed': True}
    assert workflow_errors(value)


def test_materialization_preserves_original_prose_and_every_executable_choice():
    original = claim()
    rendered = materialize_execution_claim(original)
    assert '先枚举数据' in rendered['text'] and 'new_head' in rendered['text']
    assert '每个种子分别重训基线' in rendered['text']
    assert rendered['executionSpec'] == original['executionSpec']
    assert verification_claim_view(rendered) == original
    assert materialize_execution_claim(rendered) == rendered


def test_structural_failure_never_spends_a_semantic_call_and_legacy_is_unchanged():
    c = claim()
    c['executionSpec']['order'].reverse()
    call = Mock()
    assert verify_claims([c], [], call)['rejected'][0]['reason'] == 'incomplete_experiment_workflow'
    call.assert_not_called()
    legacy = claim()
    legacy.pop('workflowContractVersion')
    legacy.pop('executionSpec')
    assert enforce_workflow_consistency(checked(legacy))['accepted'][-1] == legacy
    assert not any(c['claimId'] == 'steps' for c in enforce_workflow_consistency(checked(legacy), required=True)['accepted'])


def test_workflow_audit_requires_separate_isolation_creation_seed_and_selection_checks():
    c = claim()
    keys = {'baseline_acquisition': 'baselineMode', 'group_pairing': 'replicationMode',
        'saved_artifacts': 'records', 'data_isolation': 'order', 'component_creation': 'componentInitializations',
        'seed_pairing': 'replicationMode', 'checkpoint_selection': 'checkpointSelection'}
    audit = {'designAudit': {slot: {'fields': [{'claimId': 'steps', 'path': ['executionSpec', field],
        'value': c['executionSpec'][field]}]} for slot, field in keys.items()}}
    assert set(design_slots_for_claim(c)) == set(keys)
    assert validate_design_audit(c, audit, []) == []
    audit['designAudit'].pop('data_isolation')
    assert validate_design_audit(c, audit, []) == ['data_isolation']


def test_semantic_checker_receives_the_whole_workflow_and_all_required_audit_slots():
    from services.deep_research.tools import BudgetedSemanticChecker
    c = materialize_execution_claim(claim())
    keys = {'baseline_acquisition': 'baselineMode', 'group_pairing': 'replicationMode',
        'saved_artifacts': 'records', 'data_isolation': 'order', 'component_creation': 'componentInitializations',
        'seed_pairing': 'replicationMode', 'checkpoint_selection': 'checkpointSelection'}
    def invoke(**kwargs):
        assert 'Workflow contract 1' in kwargs['prompt']
        assert all(key in kwargs['prompt'] for key in keys)
        assert 'new_head' in kwargs['prompt'] and 'prepare_data' in kwargs['prompt']
        audit = {slot: {'fields': [{'claimId': 'steps', 'path': ['executionSpec', field],
            'value': c['executionSpec'][field]}]} for slot, field in keys.items()}
        return {'content': json.dumps([{'claimId': 'steps', 'status': 'passed', 'designAudit': audit}])}
    result = verify_claims([c], [], BudgetedSemanticChecker(invoke, 'r'))
    assert result['accepted'][0]['workflowContractVersion'] == 1


def test_referencing_a_different_definition_invalidates_prior_completion_even_with_same_display_text():
    from services.deep_research.completion_criteria import completion_contract_digest
    plan = [{'obligations': [{'obligationId': 'o', 'question': 'Design an experiment.',
        'completionCriteria': [{'criterionId': 'steps', 'requirement': 'Executable steps.', 'responseType': 'procedure'}]}]}]
    c = claim()
    previous = completion_contract_digest(plan, [c])
    changed = deepcopy(c)
    changed['executionSpec']['refs']['controls'] = 'different-controls'
    assert c['text'] == changed['text'] and previous != completion_contract_digest(plan, [changed])


@pytest.mark.parametrize('enabled', [False, True])
def test_server_opt_in_cannot_be_added_or_removed_by_synthesis(enabled):
    c = claim()
    c['workflowContractVersion'] = 999
    record = {'question': 'Propose a controlled experiment.',
              'state': {'outputKind': 'experiment_design', 'plan': [], 'evidence': []}}
    if enabled: record['workflowContractVersion'] = 1
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(run, node, prompt, options, **kwargs):
        assert ('Workflow contract 1' in prompt) is enabled
        return {'content': json.dumps({'claims': [c], 'workflowContractVersion': 999})}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    result = record['state']['reportBody']
    assert (result.get('workflowContractVersion') == 1) is enabled
    assert (result['claims'][0].get('workflowContractVersion') == 1) is enabled


def test_repair_preserves_server_marker_and_renders_revised_workflow():
    c = claim()
    revised = {**c, 'workflowContractVersion': 999, 'text': 'Revised planned steps.'}
    result = repair_rejected({'claims': [c]}, {'rejected': [{'claimId': 'steps', 'reason': 'incomplete'}]}, [],
        'Specify executable steps.', lambda _: {'content': json.dumps([revised])}, json.loads)
    assert result[0]['workflowContractVersion'] == 1 and '拟议执行流程' in result[0]['text']


def test_publish_downgrades_a_stale_workflow_if_its_referenced_definition_is_missing():
    c = claim()
    c['verification'] = 'proposal'
    record = {'workflowContractVersion': 1, 'state': {'outputKind': 'experiment_design',
        'verifiedReport': {'verifiedClaims': [c], 'rejectedClaims': [], 'answerCoverage': {'status': 'checked', 'gaps': []}}}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r', 'execution_epoch': 0})
    assert result['outcome'] != 'complete'
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_design_contract'
