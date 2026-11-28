"""Unexecuted abstract phase fixtures; no claim about Gaussian initialization science."""
from copy import deepcopy
import math
import pytest

from services.deep_research.workflow_lifecycle import lifecycle_errors, lifecycle_issues, lifecycle_budget_errors


def state(name): return {'state':name,'selector':'declared fixture state'}
def output(phase,name): return {'phaseId':phase,'outputId':name,'selector':'declared fixture output'}


def phase(name,kind,groups,reads,outputs,after,*,sharing='per_group',cap=None,updates=()):
    return {'phaseId':name,'scope':'per_frame','kind':kind,'groups':groups,'sharing':sharing,'after':after,
        'reads':reads,'updates':list(updates),'outputs':outputs,'action':{'action':'fixture '+name,'parameters':[]},
        'budget':None if cap is None else {'unit':'optimizer_steps','perExecution':cap}}


def fixture():
    return {'frameIterations':30,'componentInitializations':[
        {'componentId':'ntc','appliesTo':['0','1'],'inputs':[],
         'lifecycle':{'scope':'per_repeat','createAfter':[],'disposeAfter':None}},
        {'componentId':'added','appliesTo':['1'],'inputs':[output('stage1','selected')],
         'lifecycle':{'scope':'per_frame','createAfter':['stage1'],'disposeAfter':'record1'}}],
        'phases':[
            phase('stage1','fit',['0','1'],[state('baseline'),state('ntc'),state('training_data')],
                  ['selected','shared_state'],[],sharing='shared',cap=150,updates=['ntc']),
            phase('stage2','fit',['1'],[state('ntc'),state('added'),output('stage1','selected')],
                  ['rendered'],['stage1'],cap=150,updates=['added']),
            phase('eval0','evaluate',['0'],[state('ntc'),output('stage1','shared_state')],['metrics'],['stage2']),
            phase('eval1','evaluate',['1'],[state('ntc'),state('added'),output('stage2','rendered')],['metrics'],['eval0']),
            phase('record0','record',['0'],[state('ntc'),output('eval0','metrics')],['saved'],['eval1']),
            phase('record1','record',['1'],[state('added'),output('eval1','metrics')],['saved'],['record0'])]}


def budget():
    return {'baseline':{'mode':'train','unit':'optimizer_steps','maxBudget':100,'stoppingRule':'fixed fixture cap'},
            'recovery':{'mode':'unmatched','unit':'optimizer_steps','groups':{'0':4500,'1':9000},
                        'note':'Whole treatment includes additional fitting; no matched-budget attribution.'}}


def test_complete_per_frame_timeline_and_whole_group_budget_are_immutable():
    plan,limits=fixture(),budget();before=deepcopy((plan,limits))
    assert lifecycle_errors(plan)==[]
    assert lifecycle_budget_errors(plan,limits)==[]
    assert (plan,limits)==before


@pytest.mark.parametrize('change,code',[
    ('future_after','timeline.phase.after_future'),('cycle','timeline.cycle'),
    ('before_created','timeline.input.before_creation'),('after_disposed','timeline.input.after_disposal'),
    ('missing_output','timeline.input.output_missing'),('missing_phase','timeline.input.phase_missing'),
    ('group_leak','timeline.input.group_leak'),('frame_carry','timeline.disposal.required'),
    ('repeat_from_frame','timeline.input.scope'),('creation_scope','timeline.creation.scope'),
    ('unevaluated','timeline.evaluation.missing'),('record_without_metrics','timeline.record.evaluation_missing'),
    ('early_evaluation','timeline.evaluation.before_fit_end'),('unused','timeline.component.unused'),
    ('frame_count_bool','timeline.frameIterations'),('frame_count_zero','timeline.frameIterations'),
    ('duplicate_phase','timeline.phase.fields'),('duplicate_output','timeline.phase.outputs'),
    ('bad_action','timeline.phase.action'),('nonfit_budget','timeline.phase.nonfit_budget'),
    ('bool_budget','timeline.phase.budget'),('nonfinite_budget','timeline.phase.budget')])
def test_timeline_counterexamples_have_actionable_paths(change,code):
    plan=fixture();p=plan['phases'];c=plan['componentInitializations']
    if change=='future_after': p[0]['after']=['stage2']
    elif change=='cycle': c[1]['lifecycle']['createAfter']=['stage2']
    elif change=='before_created': c[1]['lifecycle']['createAfter']=['eval1']
    elif change=='after_disposed': c[1]['lifecycle']['disposeAfter']='stage2'
    elif change=='missing_output': c[1]['inputs'][0]['outputId']='missing'
    elif change=='missing_phase': c[1]['inputs'][0]['phaseId']='missing'
    elif change=='group_leak': p[2]['reads'].append(state('added'))
    elif change=='frame_carry': c[1]['lifecycle']['disposeAfter']=None
    elif change=='repeat_from_frame': c[1]['lifecycle']['scope']='per_repeat'
    elif change=='creation_scope': c[0]['lifecycle']['createAfter']=['stage1']
    elif change=='unevaluated': p[2]['kind']='setup'
    elif change=='record_without_metrics': p[5]['reads']=[state('added')]
    elif change=='early_evaluation': p[0]['kind']='evaluate';p[0]['budget']=None;p[0]['updates']=[]
    elif change=='unused': c.append({'componentId':'unused','appliesTo':['0'],'inputs':[],
        'lifecycle':{'scope':'per_repeat','createAfter':[],'disposeAfter':None}})
    elif change=='frame_count_bool': plan['frameIterations']=True
    elif change=='frame_count_zero': plan['frameIterations']=0
    elif change=='duplicate_phase': p[1]['phaseId']='stage1'
    elif change=='duplicate_output': p[0]['outputs'].append('selected')
    elif change=='bad_action': p[0]['action']['parameters']={}
    elif change=='nonfit_budget': p[2]['budget']={'unit':'optimizer_steps','perExecution':1}
    elif change=='bool_budget': p[0]['budget']['perExecution']=True
    else: p[0]['budget']['perExecution']=math.inf
    issues=lifecycle_issues(plan)
    assert code in [i['code'] for i in issues]
    assert all(isinstance(i['path'],str) and i['path'].startswith('/') for i in issues)


def test_disposal_can_follow_frozen_rendering_if_later_consumers_only_read_saved_outputs():
    plan=fixture();plan['componentInitializations'][1]['lifecycle']['disposeAfter']='stage2'
    plan['phases'][3]['reads']=[state('ntc'),output('stage2','rendered')]
    plan['phases'][5]['reads']=[output('eval1','metrics')]
    assert not lifecycle_errors(plan)


def test_per_repeat_manifest_after_frame_loop_and_persistent_state_disposal():
    plan=fixture();manifest=phase('manifest','record',['0','1'],[state('ntc')],['manifest'],['record1'],sharing='shared')
    manifest['scope']='per_repeat';plan['phases'].append(manifest)
    plan['componentInitializations'][0]['lifecycle']['disposeAfter']='manifest'
    assert not lifecycle_errors(plan)


def test_interleaved_frame_blocks_are_rejected():
    plan=fixture();plan['phases'][2]['scope']='per_repeat'
    assert 'timeline.frame_block' in lifecycle_errors(plan)


@pytest.mark.parametrize('bad',[None,True,[],{},1,'unknown'])
def test_malformed_scope_is_rejected_without_type_errors(bad):
    plan=fixture();plan['phases'][0]['scope']=bad
    assert 'timeline.phase.scope' in lifecycle_errors(plan)
    plan=fixture();plan['componentInitializations'][0]['lifecycle']['scope']=bad
    assert 'timeline.component.lifecycle' in lifecycle_errors(plan)


@pytest.mark.parametrize('change,code',[
    ('per_frame_as_total','timeline.budget.group_total'),('wrong_unit','timeline.budget.unit'),
    ('unknown_plan_group','timeline.budget.unknown_group'),('extra_budget_groups','timeline.budget.group_record')])
def test_whole_group_accounting_rejects_mismatches(change,code):
    plan,limits=fixture(),budget()
    if change=='per_frame_as_total': limits['recovery']['groups']={'0':150,'1':300}
    elif change=='wrong_unit': limits['recovery']['unit']='epochs'
    else:
        mapping={'0':'0','1':'10'} if change=='unknown_plan_group' else {'0':'00','1':'01'}
        for component in plan['componentInitializations']:
            component['appliesTo']=[mapping[g] for g in component['appliesTo']]
        for phase in plan['phases']: phase['groups']=[mapping[g] for g in phase['groups']]
        if change=='extra_budget_groups':
            limits['recovery']['groups']={'00':4500,'01':9000,'10':0,'11':0}
            assert 'timeline.budget.group_evaluation' in lifecycle_budget_errors(plan,limits)
    assert code in lifecycle_budget_errors(plan,limits)


def test_large_integer_budgets_are_compared_exactly_beyond_float_precision():
    plan,limits=fixture(),budget();frames=2**54;plan['frameIterations']=frames
    limits['recovery']['groups']={'0':150*frames,'1':300*frames}
    assert not lifecycle_budget_errors(plan,limits)
    limits['recovery']['groups']['1']+=1
    assert 'timeline.budget.group_total' in lifecycle_budget_errors(plan,limits)


def test_declared_decimal_seconds_do_not_need_float_tolerances():
    plan,limits=fixture(),budget()
    for p in plan['phases'][:2]:p['budget']={'unit':'wall_seconds','perExecution':0.1}
    limits['recovery'].update(unit='wall_seconds',groups={'0':3,'1':6})
    assert not lifecycle_budget_errors(plan,limits)
    limits['recovery']['groups']['1']=6.0000000001
    assert 'timeline.budget.group_total' in lifecycle_budget_errors(plan,limits)


@pytest.mark.parametrize('change,code',[
    ('evaluate','timeline.phase.evaluation_updates'),('record','timeline.phase.evaluation_updates'),
    ('training_data','timeline.phase.data_mutation'),('wrong_group','timeline.input.group_leak'),
    ('future_target','timeline.input.before_creation')])
def test_write_targets_obey_scope_lifetime_and_evaluation_boundaries(change,code):
    plan=fixture()
    if change=='evaluate': plan['phases'][3]['updates']=['added']
    elif change=='record': plan['phases'][5]['updates']=['added']
    elif change=='training_data': plan['phases'][0]['updates']=['training_data']
    elif change=='wrong_group': plan['phases'][0]['updates']=['added']
    else: plan['componentInitializations'][1]['lifecycle']['createAfter']=['eval1']
    assert code in lifecycle_errors(plan)


def test_display_events_create_and_dispose_at_declared_boundaries_without_mutation():
    from services.deep_research.workflow_lifecycle import lifecycle_events
    plan=fixture();before=deepcopy(plan);events=lifecycle_events(plan)
    assert [(e['kind'],e['id']) for e in events]==[
        ('initialize','ntc'),('phase','stage1'),('initialize','added'),('phase','stage2'),
        ('phase','eval0'),('phase','eval1'),('phase','record0'),('phase','record1'),('dispose','added')]
    events[0]['groups'].append('untrusted edit')
    events[2]['groups'].append('separate view edit')
    assert events[-1]['groups']==['1']
    assert plan==before
    plan['componentInitializations'][1]['lifecycle']['disposeAfter']='stage2'
    assert lifecycle_events(plan)==[]


def test_per_repeat_resources_precede_frame_loop_even_with_independent_reverse_listing():
    from services.deep_research.workflow_lifecycle import lifecycle_events
    plan=fixture();plan['componentInitializations'].insert(0,{'componentId':'scratch','appliesTo':['1'],'inputs':[],
        'lifecycle':{'scope':'per_frame','createAfter':[],'disposeAfter':'record1'}})
    plan['phases'][3]['reads'].append(state('scratch'))
    assert not lifecycle_errors(plan)
    events=lifecycle_events(plan)
    assert [(e['kind'],e['id']) for e in events[:2]]==[('initialize','ntc'),('initialize','scratch')]
    frame=[i for i,e in enumerate(events) if e['scope']=='per_frame']
    assert frame==list(range(frame[0],frame[-1]+1))


def test_untrusted_json_type_mutations_return_issues_without_runtime_exceptions():
    paths=[('phases',),('frameIterations',),('componentInitializations',),
        ('phases',0,'scope'),('phases',0,'after'),('phases',0,'reads'),('phases',0,'updates'),
        ('phases',0,'outputs'),('phases',0,'action'),('phases',0,'budget'),
        ('componentInitializations',0,'lifecycle'),('componentInitializations',0,'inputs'),
        ('componentInitializations',0,'appliesTo')]
    for path in paths:
        for invalid in (None,True,0,{},[None],'unknown'):
            plan=fixture();target=plan
            for key in path[:-1]:target=target[key]
            target[path[-1]]=deepcopy(invalid)
            assert lifecycle_issues(plan), (path,invalid)


def test_treatment_only_phase_output_cannot_be_read_by_control_group():
    plan=fixture();plan['phases'][2]['reads'].append(output('stage2','rendered'))
    assert 'timeline.input.group_leak' in lifecycle_errors(plan)


def test_initialization_dependency_cycle_is_rejected():
    plan=fixture();plan['componentInitializations'][0]['inputs']=[state('added')]
    assert 'timeline.cycle' in lifecycle_errors(plan)


def test_record_can_consume_a_declared_copy_of_evaluation_output():
    plan=fixture();plan['componentInitializations'].append({'componentId':'metrics_copy','appliesTo':['1'],
        'inputs':[output('eval1','metrics')],
        'lifecycle':{'scope':'per_frame','createAfter':['eval1'],'disposeAfter':'record1'}})
    plan['phases'][5]['reads']=[state('added'),state('metrics_copy')]
    assert not lifecycle_errors(plan)
