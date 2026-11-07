"""Abstract full-contract fixtures; structural acceptance does not approve science."""
from copy import deepcopy
import pytest

from test_deep_research_canonical_initialization import claims as old_claims
from test_deep_research_workflow_lifecycle import fixture, budget
from services.deep_research.experiment_workflow import workflow_errors, workflow_text, enforce_workflow_consistency
from services.deep_research.design_consistency import enforce_design_consistency
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.verification import verify_claims
from services.deep_research.completion_criteria import completion_contract_digest
from services.deep_research.experiment_diagnostics import feedback


def claims():
    rows=old_claims(); steps=rows[-1]; steps['workflowContractVersion']=5
    spec=steps['executionSpec']; initial=deepcopy(spec['baselineInitialization']); timeline=fixture()
    spec.update(frameIterations=timeline['frameIterations'],phases=timeline['phases'],componentInitializations=[])
    for component in timeline['componentInitializations']:
        init=deepcopy(initial);init.update(component)
        if component['inputs']:
            init['initializationMode']='derive'
            init['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':0},2]
        spec['componentInitializations'].append(init)
    next(c for c in rows if c['designRole']=='budget')['executionSpec']=budget()
    return rows


def test_valid_workflow5_and_control_link_have_no_diagnostic_defects():
    rows=claims(); before=deepcopy(rows)
    assert feedback(rows)=={'rules':{},'targets':{}}
    assert rows==before


def test_timeline_feedback_locates_original_bad_read_without_repairing_it():
    rows=claims();steps=rows[-1]
    steps['executionSpec']['componentInitializations'][1]['inputs'][0]['phaseId']='stage2'
    before=deepcopy(rows);result=feedback(rows)
    assert ['/executionSpec/componentInitializations/1/inputs/0','timeline.input.future_output'] in result['targets'][steps['claimId']]
    assert 'timeline.input.future_output' in result['rules']
    assert rows==before


def test_timeline_budget_feedback_uses_linked_context_and_preserves_values():
    rows=claims();steps=rows[-1]
    linked=next(c for c in rows if c['designRole']=='budget')
    linked['executionSpec']['recovery']['groups']={'0':150,'1':300}
    before=deepcopy(rows);result=feedback([steps],rows[:-1])
    assert ['/executionSpec','timeline.budget.group_total'] in result['targets'][steps['claimId']]
    assert rows==before


def test_workflow5_missing_root_feedback_has_new_version_rule_only():
    rows=claims();steps=rows[-1];del steps['executionSpec']['phases']
    result=feedback([steps],rows[:-1])
    assert ['/executionSpec','workflow5.fields'] in result['targets'][steps['claimId']]
    assert 'workflow.fields' not in result['rules']


def test_full_lifecycle_workflow_keeps_initial_values_and_round_trips_without_approval():
    rows=claims();before=deepcopy(rows);steps=rows[-1]
    assert workflow_errors(steps['executionSpec'],5)==[]
    checked=enforce_design_consistency({'accepted':rows,'rejected':[]},protocol_required=2,workflow_required=5)
    assert checked['accepted']==rows and not checked['rejected']
    assert verification_claim_view(materialize_execution_claim(steps))==steps
    assert not verify_claims([steps],[])['accepted']
    assert rows==before


def test_old_workflow_does_not_accept_new_fields_or_phase_output_inputs():
    errors=workflow_errors(claims()[-1]['executionSpec'],4)
    assert 'workflow.fields' in errors and 'workflow.component' in errors
    assert workflow_errors(old_claims()[-1]['executionSpec'],4)==[]


@pytest.mark.parametrize('change,code',[
    ('missing_state','workflow.states.required'),('symbol_dimension','workflow.states.shape'),
    ('baseline_from_future','workflow.creation.input'),('future_output','timeline.input.future_output'),
    ('disposed','timeline.input.after_disposal'),('duplicate_records','workflow.records')])
def test_new_contract_preserves_all_initialization_and_timing_guards(change,code):
    spec=claims()[-1]['executionSpec']
    if change=='missing_state': spec['baselineInitialization']['stateDefinitions']=[]
    elif change=='symbol_dimension': spec['baselineInitialization']['stateDefinitions'][0]['shape']=['N',2]
    elif change=='baseline_from_future':
        spec['baselineInitialization'].update(initializationMode='derive',inputs=[
            {'phaseId':'stage1','outputId':'selected','selector':'fixture selected state'}])
    elif change=='future_output':spec['componentInitializations'][1]['inputs'][0]['phaseId']='stage2'
    elif change=='disposed':spec['componentInitializations'][1]['lifecycle']['disposeAfter']='stage2'
    else:spec['records'].append(spec['records'][0])
    assert code in workflow_errors(spec,5)


def test_whole_group_budget_conflict_removes_steps_and_dependent_controls():
    rows=claims();next(c for c in rows if c['designRole']=='budget')['executionSpec']['recovery']['groups']={'0':150,'1':300}
    checked=enforce_design_consistency({'accepted':rows,'rejected':[]},protocol_required=2,workflow_required=5)
    assert not {'steps','controls'} & {c['claimId'] for c in checked['accepted']}
    assert any('timeline.budget.group_total' in c.get('detail','') for c in checked['rejected'])


def test_rendering_places_creation_and_disposal_in_the_frame_loop_and_escapes_markup():
    steps=claims()[-1];spec=steps['executionSpec'];spec['phases'][0]['action']['action']='fit <script>fixture</script>'
    text=workflow_text(steps)
    assert '逐帧循环' in text and '共30帧' in text
    assert '每次重复先创建所需新组件' not in text
    assert text.index('stage1 ·') < text.index('创建 added 实例') < text.index('stage2 ·')
    assert text.index('record1 ·') < text.index('释放 added 实例')
    assert 'stage1/selected' in text and '4×2' in text and '上限 150次优化更新' in text
    assert '<script>' not in text and '&lt;script&gt;' in text


def test_timeline_change_invalidates_completion_digest():
    rows=claims();plan=[{'obligations':[{'obligationId':'fixture','completionCriteria':['complete plan']}]}]
    before=completion_contract_digest(plan,rows)
    rows[-1]['executionSpec']['componentInitializations'][1]['lifecycle']['disposeAfter']='eval1'
    assert completion_contract_digest(plan,rows)!=before


def test_request_payload_cannot_override_server_lifecycle_contract(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'fixture','question':'Design',
            'workflowContractVersion':3,'executionWorkflowContractVersion':6},start_async=False)
        assert row['workflowContractVersion']==5 and row['executionWorkflowContractVersion']==7
    finally:facade.shutdown()


def test_timeline_audit_requires_complete_own_fields_not_fragments_or_other_claims():
    from services.deep_research.design_audit import _slot_supported,design_slots_for_claim
    steps=claims()[-1];spec=steps['executionSpec'];slot='timeline_dependencies'
    assert {'timeline_dependencies','state_lifetime','stage_group_accounting','evaluation_readonly'}<=set(design_slots_for_claim(steps))
    field=lambda key:{'claimId':steps['claimId'],'path':['executionSpec',key],'value':deepcopy(spec[key])}
    entry={'fields':[field('phases'),field('componentInitializations')]}
    assert _slot_supported(entry,steps,[],slot)
    assert not _slot_supported({'fields':[field('phases')]},steps,[],slot)
    assert not _slot_supported({'claimId':steps['claimId'],'quote':steps['text']},steps,[],slot)
    changed=deepcopy(entry);changed['fields'][0]['value'][0]['updates']=[]
    assert not _slot_supported(changed,steps,[],slot)
    other=deepcopy(steps);other['claimId']='other'
    wrong=deepcopy(entry)
    for f in wrong['fields']:f['claimId']='other'
    assert not _slot_supported(wrong,steps,[other],slot)
