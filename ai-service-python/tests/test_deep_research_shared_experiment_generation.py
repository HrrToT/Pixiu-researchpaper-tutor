from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest, UnknownCallError
from services.deep_research.shared_experiment_generation import MARKER, NODE, build, prepare, enabled, descriptor
from services.deep_research.design_drafting import synthesis_obligations
from services.deep_research.selection import surrounding_context
from test_deep_research_shared_experiment_plan import proposal


def context():
    from test_deep_research_comparison_intent import record
    from services.deep_research.verification import make_evidence
    r = record(); r.update(runId='r', taskId='t', question='Design a paired two-factor experiment.', startedAt=None)
    r['budget'].update(maxTokens=100000,maxWallClockSeconds=360)
    r[MARKER] = 1
    ev = make_evidence({'workId':'owned', 'versionId':'v1', 'contentHash':'hash', 'accessLevel':'fulltext'},
        'An exact public source statement.', 'An exact public source statement.', location={}, obligation_ids=['G1'])
    r['state'].update(outputKind='experiment_design', evidence=[ev], plan=[{'itemId':'design',
        'obligations':[{'obligationId':'G1', 'question':r['question'], 'purpose':'answer_requirement',
            'completionCriteria':[{'criterionId':'complete', 'requirement':'Complete paired protocol', 'responseType':'explanation'}]}]}])
    row = {'evidenceId':'E1', 'source':'P1', 'quote':ev['quote'], 'sourceContext':surrounding_context(ev),
           'accessLevel':ev['accessLevel'], 'location':ev.get('location', {}), 'obligations':['G1']}
    data = {'question':r['question'], 'requirements':synthesis_obligations(r['state']['plan']),
            'sources':{'P1':{'workId':'owned', 'title':'Fixture publication'}}, 'evidence':[row], 'tables':{}}
    return r, data, {'E1':ev['evidenceId']}


def response(value=None, **kwargs):
    return {'content':json.dumps(proposal() if value is None else value), 'finishReason':'stop', **kwargs}


def harness(r):
    current = deepcopy(r); states = []
    def checkpoint(v):
        current['state']['sharedExperimentGeneration'] = deepcopy(v); states.append(deepcopy(v))
    return current, states, checkpoint


@pytest.mark.parametrize('version', [None, 0, True, '1', 2, 3, 4, 5, 6, 7, 8, 9])
def test_legacy_and_invalid_policy_do_not_select_new_transport(version):
    from services.deep_research.planning_transport import enabled as transport_enabled
    r, data, aliases = context(); r[MARKER] = version
    if version in (2, 3, 4, 5, 6, 7, 8):
        assert enabled(r) and transport_enabled(r, NODE)
        return
    assert not enabled(r) and not transport_enabled(r, NODE)
    with pytest.raises(ValueError): build(r, data, aliases)


def test_topology_guidance_is_bound_to_the_new_run_and_validates_the_same_plan():
    r, data, aliases = context()
    old = build(r, data, aliases)
    r[MARKER] = 2
    new = build(r, data, aliases)
    assert new['contextDigest'] == old['contextDigest']
    assert new['allowedEvidenceIds'] == old['allowedEvidenceIds']
    assert new['inputDigest'] != old['inputDigest']
    assert 'A0 groups=["00","01"]' in new['request']['prompt']
    assert 'Measure steps have creates=[], updates=[]' in new['request']['prompt']
    assert 'A0 groups=' not in old['request']['prompt']
    current, states, checkpoint = harness(r)
    proposal_with_wrong_budget = proposal()
    clone = next(step for step in proposal_with_wrong_budget['steps'] if step['kind'] == 'clone')
    clone['budgetId'] = next(budget['id'] for budget in proposal_with_wrong_budget['budgets'] if budget['scope'] == 'shared')
    invoke = Mock(return_value=response(proposal_with_wrong_budget))
    with pytest.raises(DeepResearchError, match='共享方案未通过检查'):
        prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert states[-1]['status'] == 'invalid_response' and not states[-1].get('boundProposal')
    assert any(issue['code'] == 'plan.budget_reference' for issue in states[-1]['issues'])
    invoke.assert_called_once()


def test_frozen_prerequisite_policy_places_acquisition_and_stops_in_the_plan():
    from services.deep_research.shared_experiment_generation import PREREQUISITE_PLACEMENT_MARKER

    r, data, aliases = context()
    r[MARKER] = 8
    legacy = build(r, data, aliases)
    r[PREREQUISITE_PLACEMENT_MARKER] = 1
    current = build(r, data, aliases)
    assert current['contextDigest'] == legacy['contextDigest']
    assert current['allowedEvidenceIds'] == legacy['allowedEvidenceIds']
    assert current['inputDigest'] != legacy['inputDigest']
    prompt = current['request']['prompt']
    assert 'acquisition, acceptance checks and stop conditions in shared preparation' in prompt
    assert 'Use unresolved only for unanswered scientific or design decisions' in prompt
    assert 'Do not claim the prerequisite is already met.' in prompt
    assert 'Use unresolved only for unanswered' not in legacy['request']['prompt']


def test_single_generation_is_durable_unchecked_and_reused_without_second_send():
    r, data, aliases = context(); current, states, checkpoint = harness(r); invoke = Mock(return_value=response())
    result = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert [s['status'] for s in states] == ['pending', 'response_received', 'awaiting_scientific_review']
    assert result['scientificApproval'] is False and result['boundProposal']['scientificApproval'] is False
    assert result['status'] == 'awaiting_scientific_review' and result['response'] == response()
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
    assert invoke.call_count == 1 and 'reportBody' not in current['state']


def reference_draft(canonical):
    draft = deepcopy(canonical)
    for state in draft['states']:
        if state['source']['kind'] == 'step':
            state['source'] = None
    for step in draft['steps']:
        if step['kind'] == 'intervene':
            step['operation'] = None
    return draft


def owned_states_draft(canonical):
    draft = reference_draft(canonical)
    state_defs = {}
    initial_states = []
    for state in draft['states']:
        state_defs[state['id']] = {key: value for key, value in state.items()
                                  if key not in ('source', 'scope', 'groups')}
        if state['source'] is not None:
            initial_states.append({**state_defs[state['id']], 'source': state['source']})
    draft['states'] = initial_states
    for metric in draft['metrics']:
        metric['measureOnSteps'] = [step['id'] for step in draft['steps'] if metric['id'] in step['metricIds']]
    for step in draft['steps']:
        step['creates'] = [state_defs[state_id] for state_id in step['creates']]
        del step['metricIds']
    return draft


def typed_input_proposal():
    canonical = proposal()
    canonical['version'] = 2
    canonical['data']['inputs'][0]['availability'] = 'provided'
    for step in canonical['steps']:
        step['inputIds'] = ['input'] if step['dataUse'] != 'none' else []
    return canonical


def asset_catalog_draft(canonical):
    draft = owned_states_draft(canonical)
    states = draft.pop('states')
    data = draft['data']
    data['providedInputs'] = []
    data['inputsToPrepare'] = []
    for asset in data.pop('inputs'):
        if asset.pop('availability') == 'provided':
            asset['initialStates'] = [
                {key: value for key, value in state.items() if key != 'source'}
                for state in states if state['source']['id'] == asset['id']
            ]
            data['providedInputs'].append(asset)
        else:
            data['inputsToPrepare'].append(asset)
    return draft


def test_owned_states_profile_preserves_assets_creators_and_observation_links():
    r, data, aliases = context()
    r[MARKER] = 4
    canonical = typed_input_proposal()
    draft = owned_states_draft(canonical)
    reply = response(draft)
    current, states, checkpoint = harness(r)
    invoke = Mock(return_value=reply)
    result = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert result['boundProposal']['proposal'] == canonical
    assert result['response'] == reply
    assert 'shared_binary_factorial_states_v4' in json.dumps(result['request'])
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
    invoke.assert_called_once()


@pytest.mark.parametrize('fault,code', [
    ('missing_control', 'plan.factor_state'),
    ('missing_asset', 'plan.step_input_identity'),
    ('unprepared_asset', 'plan.step_input_unavailable'),
    ('asset_read_as_state', 'plan.future_state'),
    ('measure_writes_state', 'plan.measurement_mutation'),
    ('fit_as_measure', 'plan.measurement_reference'),
])
def test_owned_states_profile_rejects_invalid_role_binding(fault, code):
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    draft = owned_states_draft(canonical)
    fit = draft['steps'][0]
    if fault == 'missing_control':
        draft['steps'][1]['creates'].pop(0)
    elif fault == 'missing_asset':
        fit['inputIds'] = ['missing']
    elif fault == 'unprepared_asset':
        draft['data']['inputs'].append({
            **draft['data']['inputs'][0], 'id': 'second', 'availability': 'prepare',
        })
        fit['inputIds'].append('second')
    elif fault == 'asset_read_as_state':
        fit['reads'].append('input')
    elif fault == 'measure_writes_state':
        draft['steps'][-1]['updates'].append('x')
    else:
        draft['metrics'][0]['measureOnSteps'] = [fit['id']]
    compiled, issues = compile_plan(draft, ['E1'], profile=4)
    assert compiled is None
    assert code in {issue['code'] for issue in issues}


def test_owned_states_profile_keeps_prepared_asset_available_after_shared_step():
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    canonical['data']['inputs'].append({
        'id': 'dataset', 'description': 'Development dataset', 'availability': 'prepare',
        'preparation': 'Download and verify the manifest before splitting.', 'sourceFactIds': [],
    })
    fit = canonical['steps'][0]
    preparation = {**fit, 'id': 'download', 'kind': 'prepare', 'inputIds': ['dataset'],
                   'reads': [], 'updates': [], 'budgetId': None,
                   'operation': {'action': 'Download and verify the manifest.', 'parameters': []}}
    canonical['steps'].insert(0, preparation)
    fit['inputIds'].append('dataset')
    compiled, issues = compile_plan(owned_states_draft(canonical), ['E1'], profile=4)
    assert not issues
    assert compiled == canonical


@pytest.mark.parametrize('fault,code', [
    (None, None),
    ('pending_initial_state', 'plan.wire_schema'),
    ('read_before_creation', 'plan.future_state'),
    ('duplicate_clone_state', 'plan.duplicate_identity'),
])
def test_asset_catalog_binds_pending_state_to_the_preparing_step(fault, code):
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    asset = canonical['data']['inputs'][0]
    asset['availability'] = 'prepare'
    initial = next(state for state in canonical['states'] if state['source']['kind'] == 'input')
    initial['source'] = {'kind': 'step', 'id': 'prepare_inputs'}
    fit = canonical['steps'][0]
    canonical['steps'].insert(0, {**fit, 'id': 'prepare_inputs', 'kind': 'prepare',
                                  'reads': [], 'updates': [], 'creates': [initial['id']], 'budgetId': None,
                                  'operation': {'action': 'Verify inputs and prepare initial state.', 'parameters': []}})
    draft = asset_catalog_draft(canonical)
    prepare_step = draft['steps'][0]
    if fault == 'pending_initial_state':
        draft['data']['inputsToPrepare'][0]['initialStates'] = prepare_step['creates']
    elif fault == 'read_before_creation':
        prepare_step['reads'] = [initial['id']]
    elif fault == 'duplicate_clone_state':
        clone = next(step for step in draft['steps'] if step['kind'] == 'clone')
        draft['steps'].append({**clone, 'id': 'duplicate_clone'})
    compiled, issues = compile_plan(draft, ['E1'], profile=6)
    if code:
        assert compiled is None and code in {issue['code'] for issue in issues}
    else:
        assert not issues and compiled == canonical


def test_explicit_clone_layout_uses_nine_components_for_four_independent_arms():
    from services.deep_research.shared_experiment_generation import CLONE_LAYOUT_MARKER
    from services.deep_research.shared_experiment_plan import GROUPS

    r, data, aliases = context()
    r[MARKER] = 6
    legacy = build(r, data, aliases)
    r[CLONE_LAYOUT_MARKER] = 1
    current, _, checkpoint = harness(r)
    canonical = typed_input_proposal()
    clone = next(step for step in canonical['steps'] if step['kind'] == 'clone')
    for identity in ('arm_optimizer', 'position', 'scale', 'rotation', 'opacity', 'sh', 'treatment_control'):
        clone['creates'].append(identity)
        canonical['states'].append({'id': identity, 'meaning': f'Local {identity}',
            'representation': 'Snapshot copied from the paired common state', 'scope': 'arm',
            'groups': list(GROUPS), 'fixed': False, 'persisted': False, 'source': {'kind': 'step', 'id': clone['id']}})
    draft = asset_catalog_draft(canonical)
    reply = response(draft)
    invoke = Mock(return_value=reply)
    saved = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    prompt = saved['request']['prompt']
    assert 'scope="arm", groups=["00","10","01","11"]' in prompt
    assert 'each arm reads/updates its own arm_optimizer under that same ID' in prompt
    assert 'arm_optimizer' not in legacy['request']['prompt']
    assert saved['contextDigest'] == legacy['contextDigest'] and saved['inputDigest'] != legacy['inputDigest']
    assert saved['boundProposal']['proposal'] == canonical
    assert len(clone['creates']) == 9 and clone['groups'] == list(GROUPS)
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == saved
    invoke.assert_called_once()


def test_complete_padded_response_can_fit_canonical_plan_under_profile_5():
    r, data, aliases = context()
    r[MARKER] = 4
    prior = build(r, data, aliases)
    r[MARKER] = 5
    canonical = typed_input_proposal()
    padded = ' ' * 25000 + json.dumps(owned_states_draft(canonical), indent=2)
    reply = response(rawContent=padded)
    current, _, checkpoint = harness(r)
    invoke = Mock(return_value=reply)
    saved = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert saved['boundProposal']['proposal'] == canonical
    assert saved['response']['rawContent'] == padded
    assert saved['request']['extra']['max_tokens'] == invoke.call_args.args[2]['max_tokens'] == 9216
    assert prior['request']['extra']['max_tokens'] == 6144
    assert descriptor(4) == descriptor(5)
    assert prior['contextDigest'] == saved['contextDigest']
    assert prior['inputDigest'] != saved['inputDigest']
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == saved
    invoke.assert_called_once()


@pytest.mark.parametrize('fault,code', [
    (None, None),
    ('explicit_groups', 'plan.wire_schema'),
    ('missing_clone_operation', 'plan.wire_schema'),
    ('missing_level', 'plan.intervention_coverage'),
])
def test_factorial_compiler_derives_arms_from_each_explicit_factor_level(fault, code):
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    draft = asset_catalog_draft(canonical)
    interventions = [step for step in draft['steps'] if step['kind'] == 'intervene']
    assert len(interventions) == 4
    for step in interventions:
        step['groups'] = []
    if fault == 'explicit_groups':
        interventions[0]['groups'] = ['00', '10', '01', '11']
    elif fault == 'missing_clone_operation':
        next(step for step in draft['steps'] if step['kind'] == 'clone')['operation'] = None
    elif fault == 'missing_level':
        draft['steps'].remove(interventions[0])

    compiled, issues = compile_plan(draft, ['E1'], profile=7)
    if code:
        assert compiled is None and code in {issue['code'] for issue in issues}
    else:
        assert not issues and compiled == canonical
        assert all(not step['groups'] for step in interventions)
        r, data, aliases = context()
        r[MARKER] = 7
        current, _, checkpoint = harness(r)
        invoke = Mock(return_value=response(draft))
        saved = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
        assert 'Write four distinct intervene steps' in saved['request']['prompt']
        assert saved['boundProposal']['proposal'] == canonical
        invoke.assert_called_once()


@pytest.mark.parametrize('fault,code', [
    (None, None),
    ('per_step_reuse', 'plan.budget_allocation'),
    ('disjoint_preparation', 'plan.shared_preparation_budget'),
    ('allocated_to_fit', 'plan.shared_preparation_budget'),
    ('record_from_clone', 'plan.fit_memory_capture'),
    ('missing_measurement_read', 'plan.fit_memory_capture_read'),
    ('missing_fit_interval', 'plan.fit_memory_capture'),
    ('storage_without_persisted_states', 'plan.incomplete_resource_accounting'),
])
def test_shared_preparation_cap_and_arm_peak_memory_have_distinct_accounting(fault, code):
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    canonical['version'] = 3
    preflight = canonical['steps'][0]
    preflight.update(kind='prepare', dataUse='none', inputIds=[], updates=[])
    canonical['steps'].insert(1, {**preflight, 'id':'prepare_checkpoint'})
    common, matched = canonical['budgets']
    common.update(unit='wall_seconds', matching='native', allocation='shared_preparation_total',
                  stopRule='Stop if the continuous preparation cap expires. Skip all arms if incomplete.')
    matched['allocation'] = 'single'
    fit, measure = canonical['steps'][-2:]
    fit['creates'].append('peak')
    canonical['states'].append({'id':'peak', 'meaning':'Per-arm fit peak allocator reading',
        'representation':'One peak count in bytes for each paired run', 'fixed':True, 'persisted':False,
        'scope':'arm', 'groups':list(fit['groups']), 'source':{'kind':'step','id':fit['id']}})
    measure['reads'].append('peak')
    measure['metricIds'].append('memory')
    canonical['analysis']['metricIds'].append('memory')
    for metric in canonical['metrics']:
        metric['fitMemoryCaptures'] = []
    memory = {'id':'memory','domain':'memory','unit':'bytes','direction':'lower_better','stateIds':['peak'],
              'procedure':'Reset the allocator peak immediately before fit, synchronize and read peak before teardown.',
              'fitMemoryCaptures':[{'stepId':fit['id'],'recordStateId':'peak'}]}
    canonical['metrics'].append(memory)
    if fault == 'per_step_reuse':
        common['allocation'] = 'single'
    elif fault == 'disjoint_preparation':
        canonical['steps'].insert(1, {**preflight, 'id':'separate', 'budgetId':None})
    elif fault == 'allocated_to_fit':
        preflight.update(kind='fit', dataUse='training')
    elif fault == 'record_from_clone':
        memory['fitMemoryCaptures'][0]['recordStateId'] = 'x'
        memory['stateIds'].append('x')
    elif fault == 'missing_measurement_read':
        measure['reads'].remove('peak')
    elif fault == 'missing_fit_interval':
        canonical['steps'].insert(-1, {**fit, 'id':'additional_fit', 'creates':[], 'budgetId':'extra'})
        canonical['budgets'].append({**matched,'id':'extra'})
    elif fault == 'storage_without_persisted_states':
        next(metric for metric in canonical['metrics'] if metric['domain']=='storage')['stateIds'] = ['peak']
    draft = asset_catalog_draft(canonical)
    for step in draft['steps']:
        if step['kind'] == 'intervene':
            step['groups'] = []
    result, issues = compile_plan(draft, ['E1'], profile=8)
    if code:
        assert result is None and code in {issue['code'] for issue in issues}
    else:
        assert not issues and result == canonical
        pairing_wire = deepcopy(draft)
        pairing_wire['pairing'] = {'identityChecks': draft['pairing']['identityChecks']}
        derived, pairing_issues = compile_plan(pairing_wire, ['E1'], profile=8, derive_pairing=True)
        assert not pairing_issues
        assert derived == {**canonical, 'pairing': {**canonical['pairing'],
                           'sharedStateIds': sorted(canonical['pairing']['sharedStateIds'])}}
        assert compile_plan(draft, ['E1'], profile=8, derive_pairing=True)[0] is None
        wire = deepcopy(pairing_wire)
        del wire['analysis']['metricIds']
        for row in (wire['steps'][0], wire['budgets'][0]):
            row['groups'] = ['11', '01', '00', '10']
        assert compile_plan(wire, ['E1'], profile=8, derive_pairing=True,
                            derive_analysis=True) == (derived, [])
        assert compile_plan(pairing_wire, ['E1'], profile=8, derive_pairing=True,
                            derive_analysis=True)[0] is None
        wire['steps'][0]['groups'].pop()
        invalid, issues = compile_plan(wire, ['E1'], profile=8, derive_pairing=True, derive_analysis=True)
        assert invalid is None and {'code':'plan.step_scope','path':'/steps/0'} in issues
        clone = next(step for step in pairing_wire['steps'] if step['kind'] == 'clone')
        clone['reads'].append('not_created')
        invalid, invalid_issues = compile_plan(pairing_wire, ['E1'], profile=8, derive_pairing=True)
        assert invalid is None and any(issue['code'] == 'plan.future_state' for issue in invalid_issues)
        annotated = deepcopy(draft)
        for factor in annotated['factors']:
            factor['affectedStateIds'].append('peak')
        annotated['steps'][-2]['updates'].append('peak')
        assert compile_plan(annotated, ['E1'], profile=8)[0] is None
        assert compile_plan(annotated, ['E1'], profile=8, fit_observation_outputs=True) == (canonical, [])
        intervention = next(step for step in annotated['steps'] if step['kind'] == 'intervene')
        intervention['reads'].append('peak')
        invalid, invalid_issues = compile_plan(annotated, ['E1'], profile=8, fit_observation_outputs=True)
        assert invalid is None and any(issue['code'] == 'plan.future_state' for issue in invalid_issues)
        record, data, aliases = context()
        record[MARKER] = 8
        current, _, checkpoint = harness(record)
        invoke = Mock(return_value=response(draft))
        saved = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
        assert saved['boundProposal']['proposal'] == canonical and saved['scientificApproval'] is False
        invoke.assert_called_once()
        from services.deep_research.shared_experiment_review import build as build_review
        from services.deep_research.shared_experiment_result import compile_candidate
        from test_deep_research_shared_experiment_review import check
        current['state']['sharedExperimentGeneration'] = saved
        built = build_review(current,data,aliases)
        assert built['suppliedEvidenceAliases'] == ['E1']
        assert any('continuous wall-clock cap' in target['requirement'] for target in built['targets'])
        result, _, _, _ = check(current,data,aliases)
        assert result['assessment']['complete']
        report = compile_candidate(current,data,aliases)
        assert report['markdown'].count('共用 100 秒准备预算') == 1
        assert '完整拟合窗口记录峰值' in report['markdown']
        assert report['publishable'] is False
        assert '对每个实验组取本组各拟合窗口中的最大值' in report['markdown']

        from services.deep_research.shared_experiment_result import MEMORY_REPORT_MARKER
        current[MEMORY_REPORT_MARKER] = 1
        scoped_report = compile_candidate(current,data,aliases)
        assert '按配对重复分开，每组取当次完整窗口中的最大值' in scoped_report['markdown']
        assert '对每个实验组取本组各拟合窗口中的最大值' not in scoped_report['markdown']
        assert scoped_report['generationBindingDigest'] == report['generationBindingDigest']
        assert scoped_report['reviewDigest'] == report['reviewDigest']


@pytest.mark.parametrize('failure,code', [
    ('truncated', 'plan.incomplete_response'),
    ('transport_capacity', 'plan.response_transport_capacity'),
    ('canonical_capacity', 'plan.capacity'),
])
def test_profile_5_still_stops_and_retains_oversized_or_incomplete_response(failure, code):
    r, data, aliases = context()
    r[MARKER] = 5
    if failure == 'truncated':
        reply = {'rawContent': '{' + ' ' * 25718, 'finishReason': 'length'}
    elif failure == 'transport_capacity':
        reply = response(rawContent=' ' * 48001)
    else:
        draft = owned_states_draft(typed_input_proposal())
        draft['unresolved'] = [str(i) + 'X' * 1560 for i in range(16)]
        reply = response(draft)
    current, states, checkpoint = harness(r)
    invoke = Mock(return_value=reply)
    with pytest.raises(DeepResearchError, match='共享方案未通过检查'):
        prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert states[-1]['response'] == reply and states[-1]['status'] == 'invalid_response'
    assert states[-1]['issues'] == [{'code': code, 'path': '/'}]
    assert 'boundProposal' not in states[-1]
    with pytest.raises(DeepResearchError, match='共享方案未通过检查'):
        prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    invoke.assert_called_once()


@pytest.mark.parametrize('fault,expected', [
    ('none', None),
    ('training_read', 'plan.evaluation_state_leakage'),
    ('clone_read', 'plan.evaluation_state_leakage'),
    ('prepare_update', 'plan.evaluation_preparation_scope'),
    ('prepare_mutable_reference', 'plan.evaluation_preparation_scope'),
    ('prepare_unavailable_input', 'plan.step_input_unavailable'),
    ('measurement_without_read', 'plan.evaluation_state_leakage'),
    ('measurement_before_registration', 'plan.future_state'),
])
def test_shared_evaluation_preparation_is_visible_only_to_evaluation(fault, expected):
    from services.deep_research.shared_experiment_references import compile_plan

    canonical = typed_input_proposal()
    canonical['version'] = 3
    preflight = canonical['steps'][0]
    preflight.update(kind='prepare', dataUse='none', inputIds=[], updates=[])
    canonical['states'][0]['fixed'] = True
    common, matched = canonical['budgets']
    common.update(unit='wall_seconds', matching='native', allocation='shared_preparation_total')
    matched['allocation'] = 'single'
    registration = {**preflight, 'id': 'register', 'dataUse': 'evaluation_prepare',
                    'reads': [canonical['states'][0]['id']], 'creates': ['test_poses']}
    canonical['steps'].insert(1, registration)
    canonical['states'].append({
        'id': 'test_poses', 'meaning': 'Accepted test cameras',
        'representation': 'Frozen registered camera matrices', 'fixed': True, 'persisted': False,
        'scope': 'shared', 'groups': [], 'source': {'kind': 'step', 'id': 'register'},
    })
    fit, measure = canonical['steps'][-2:]
    measure['reads'].append('test_poses')
    canonical['metrics'][0]['stateIds'].append('test_poses')
    for metric in canonical['metrics']:
        metric['fitMemoryCaptures'] = []
    if fault == 'training_read':
        fit['reads'].append('test_poses')
    elif fault == 'clone_read':
        canonical['steps'][2]['reads'].append('test_poses')
    elif fault == 'prepare_update':
        registration['updates'] = registration['reads'].copy()
    elif fault == 'prepare_mutable_reference':
        canonical['states'][0]['fixed'] = False
    elif fault == 'prepare_unavailable_input':
        canonical['data']['inputs'].append({
            'id': 'test_input', 'description': 'Unacquired test calibration', 'availability': 'prepare',
            'preparation': 'Obtain the test calibration before registration.', 'sourceFactIds': [],
        })
        registration['inputIds'] = ['test_input']
    elif fault == 'measurement_without_read':
        measure['reads'].remove('test_poses')
    elif fault == 'measurement_before_registration':
        canonical['steps'].append(canonical['steps'].pop(1))
    draft = asset_catalog_draft(canonical)
    for step in draft['steps']:
        if step['kind'] == 'intervene':
            step['groups'] = []
    assert compile_plan(draft, ['E1'], profile=8)[0] is None
    bound, issues = compile_plan(draft, ['E1'], profile=8, evaluation_prepare=True)
    if expected:
        assert bound is None and expected in {issue['code'] for issue in issues}
    else:
        assert not issues
        order = lambda plan: sorted(plan['states'], key=lambda x: x['id'])
        assert {**bound, 'states': order(bound)} == {**canonical, 'states': order(canonical)}


def test_reference_profile_resolves_the_canonical_plan_and_reuses_raw_receipt():
    r, data, aliases = context()
    r[MARKER] = 2
    previous = build(r, data, aliases)
    r[MARKER] = 3
    new = build(r, data, aliases)
    assert new['contextDigest'] == previous['contextDigest']
    assert new['inputDigest'] != previous['inputDigest']
    assert 'operation=null' in new['request']['prompt']
    assert 'shared_binary_factorial_refs_v3' in json.dumps(new['request'])
    canonical = proposal()
    canonical['data']['inputs'][0]['availability'] = 'provided'
    reply = response(reference_draft(canonical))
    current, states, checkpoint = harness(r)
    invoke = Mock(return_value=reply)
    result = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert result['response'] == reply
    assert result['boundProposal']['proposal'] == canonical
    assert result['status'] == 'awaiting_scientific_review'
    assert result['boundProposal']['scientificApproval'] is False
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
    invoke.assert_called_once()


@pytest.mark.parametrize('fault,code', [
    ('missing_creator', 'plan.state_creator_reference'),
    ('duplicate_creator', 'plan.state_creator_reference'),
    ('competing_input', 'plan.state_input_also_created'),
    ('unprepared_input', 'plan.state_input_unavailable'),
    ('local_operation', 'plan.intervention_operation_reference'),
    ('missing_operation', 'plan.operation_required'),
    ('future_read', 'plan.future_state'),
])
def test_reference_profile_rejects_unresolved_or_unsafe_drafts(fault, code):
    r, data, aliases = context()
    r[MARKER] = 3
    canonical = proposal()
    canonical['data']['inputs'][0]['availability'] = 'provided'
    draft = reference_draft(canonical)
    created = next(state for state in draft['states'] if state['source'] is None)
    creator = next(step for step in draft['steps'] if created['id'] in step['creates'])
    first_step = draft['steps'][0]
    if fault == 'missing_creator':
        creator['creates'].remove(created['id'])
    elif fault == 'duplicate_creator':
        next(step for step in draft['steps'] if step != creator)['creates'].append(created['id'])
    elif fault == 'competing_input':
        created['source'] = {'kind': 'input', 'id': draft['data']['inputs'][0]['id']}
    elif fault == 'unprepared_input':
        input_id = next(state['source']['id'] for state in draft['states'] if state['source'] is not None)
        next(row for row in draft['data']['inputs'] if row['id'] == input_id)['availability'] = 'prepare'
    elif fault == 'local_operation':
        index = next(i for i, step in enumerate(draft['steps']) if step['kind'] == 'intervene')
        draft['steps'][index]['operation'] = canonical['steps'][index]['operation']
    elif fault == 'missing_operation':
        first_step['operation'] = None
    else:
        assert draft['steps'].index(first_step) < draft['steps'].index(creator)
        first_step['reads'].append(created['id'])
    current, states, checkpoint = harness(r)
    reply = response(draft)
    invoke = Mock(return_value=reply)
    with pytest.raises(DeepResearchError, match='共享方案未通过检查'):
        prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert states[-1]['response'] == reply
    assert states[-1]['status'] == 'invalid_response'
    assert 'boundProposal' not in states[-1]
    assert code in {issue['code'] for issue in states[-1]['issues']}
    invoke.assert_called_once()


def test_single_json_fence_is_removed_for_validation_only():
    r, data, aliases = context()
    current, states, checkpoint = harness(r)
    reply = response()
    reply['rawContent'] = '```json\n' + reply['content'] + '\n```'
    invoke = Mock(return_value=reply)
    saved = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert saved['status'] == 'awaiting_scientific_review' and saved['scientificApproval'] is False
    assert saved['response']['rawContent'] == reply['rawContent']
    assert invoke.call_count == 1


@pytest.mark.parametrize('kind', ['duplicate', 'foreign_text', 'invalid_plan'])
def test_fenced_response_still_requires_strict_input_and_plan_validation(kind):
    r, data, aliases = context()
    current, states, checkpoint = harness(r)
    reply = response()
    body = reply['content']
    if kind == 'duplicate':
        body = body.replace('"version": 1', '"version": 1, "version": 1', 1)
    elif kind == 'invalid_plan':
        wrong = proposal()
        wrong['groups'][0]['levels']['A'] = 1
        body = json.dumps(wrong)
    reply['rawContent'] = '```json\n' + body + '\n```'
    if kind == 'foreign_text':
        reply['rawContent'] += '\nAnother conclusion.'
    invoke = Mock(return_value=reply)
    with pytest.raises(DeepResearchError, match='共享方案未通过检查'):
        prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert states[-1]['status'] == 'invalid_response' and 'boundProposal' not in states[-1]
    assert states[-1]['response'] == reply and invoke.call_count == 1


@pytest.mark.parametrize('mutation', ['question', 'goal', 'quote', 'context', 'source', 'publication', 'location', 'alias', 'table'])
def test_changed_original_context_stops_before_request_or_checkpoint(mutation):
    r, data, aliases = context(); invoke = Mock(); saved = []
    if mutation == 'question': data['question'] += ' changed'
    elif mutation == 'goal': data['requirements'][0]['question'] += ' changed'
    elif mutation == 'quote': data['evidence'][0]['quote'] += ' invented'
    elif mutation == 'context': data['evidence'][0]['sourceContext'] = {'before':'invented', 'after':'', 'truncated':False}
    elif mutation == 'source': data['sources']['P1']['workId'] = 'foreign'
    elif mutation == 'publication': data['sources']['P1']['publicationIdentity'] = {'revision':'v99'}
    elif mutation == 'location': data['evidence'][0]['location'] = {'page':999}
    elif mutation == 'alias': aliases['E2'] = aliases['E1']
    else: data['evidence'][0]['tableData'] = {'rows':['invented']}
    with pytest.raises(ValueError): prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append)
    invoke.assert_not_called(); assert not saved


def test_native_schema_and_actual_input_window_are_counted_before_send():
    r, data, aliases = context()
    # Change both authoritative source and wire row. Repetitions are not used:
    # string sharing cannot hide this unique source's size.
    large = ''.join(chr(0x4e00+i) for i in range(14000))
    r['state']['evidence'][0]['quote'] = large; data['evidence'][0]['quote'] = large
    r['state']['evidence'][0]['sourceContext'] = large
    data['evidence'][0]['sourceContext'] = surrounding_context(r['state']['evidence'][0])
    invoke = Mock(); saved = []
    with pytest.raises(DeepResearchError) as error: prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append)
    assert error.value.code == 'shared_experiment_input_capacity'
    assert saved[-1]['inputBytes'] > 32000 and saved[-1]['transportOverheadBytes'] > 7000
    invoke.assert_not_called()


def test_call_floor_counts_both_spent_pools_and_stops_without_waiving_reviews():
    r, data, aliases = context(); r['budget'].update(modelCalls=10, reservedModelCalls=3)
    saved = []; invoke = Mock()
    assert prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append) is None
    assert saved[-1]['status'] == 'not_started_budget' and saved[-1]['remainingModelCallsAtPreparation'] == 5
    invoke.assert_not_called()


@pytest.mark.parametrize('kind', ['length', 'duplicate', 'invalid_plan', 'malformed', 'missing_finish'])
def test_invalid_reply_is_saved_and_never_auto_retried(kind):
    r, data, aliases = context(); current, states, checkpoint = harness(r); reply = response()
    if kind == 'length': reply['finishReason'] = 'length'
    elif kind == 'duplicate': reply['content'] = reply['content'].replace('"version": 1', '"version": 1,"version":1', 1)
    elif kind == 'invalid_plan':
        p = proposal(); p['groups'][0]['levels']['A'] = 1; reply = response(p)
    elif kind == 'missing_finish': reply.pop('finishReason')
    else: reply['content'] = '{'
    invoke = Mock(return_value=reply)
    for _ in range(2):
        with pytest.raises(DeepResearchError) as error: prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
        assert error.value.code == 'invalid_shared_experiment_response'
    assert invoke.call_count == 1 and states[-1]['status'] == 'invalid_response'
    assert states[-1]['response'] == reply and not states[-1].get('boundProposal')


def test_unknown_invocation_is_not_reentered_on_resume():
    r, data, aliases = context(); current, states, checkpoint = harness(r)
    invoke = Mock(side_effect=UnknownCallError('unknown-original'))
    with pytest.raises(UnknownCallError): prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    with pytest.raises(DeepResearchError) as error: prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert error.value.code == 'shared_experiment_invocation_stopped' and invoke.call_count == 1


@pytest.mark.parametrize('mutation', ['response', 'binding', 'context', 'approval_type'])
def test_saved_state_tampering_does_not_send_again(mutation):
    r, data, aliases = context(); current, _, checkpoint = harness(r); invoke = Mock(return_value=response())
    prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    saved = current['state']['sharedExperimentGeneration']
    if mutation == 'response': saved['response']['content'] = '{}'
    elif mutation == 'binding': saved['boundProposal']['proposal']['budgets'][1]['cap'] = 99
    elif mutation == 'context': saved['contextDigest'] = digest('changed')
    else: saved['scientificApproval'] = 0
    with pytest.raises(DeepResearchError): prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert invoke.call_count == 1


def test_default_facade_freezes_zero_even_if_client_requests_enablement(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId':'t', 'operationKey':'op', 'question':'Design an experiment', MARKER:1}, start_async=False)
        assert r[MARKER] == 0 and not enabled(r)
        for v in (1, True, None):
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda r: {**r, MARKER:v})
    finally: facade.shutdown()


@pytest.mark.parametrize('provider_result', ['success', 'timeout', 'checkpoint_crash'])
def test_actual_tracked_scoped_http_schema_and_receipt_reuse(tmp_path, monkeypatch, provider_result):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.planning_transport import overhead_bytes
    from llm.client import DeepSeekLLM, LLMProviderError
    import requests
    from test_deep_research_schema_transport import response as http_response
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    r, data, aliases = context(); repo.create_run(r); repo.begin_execution('r')
    post = (Mock(side_effect=requests.Timeout('fixture timeout')) if provider_result == 'timeout'
            else Mock(return_value=http_response(json.dumps(proposal()))))
    monkeypatch.setattr('llm.client.requests.post', post)
    provider = DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')
    scoped = ScopedModelClient(repo, lambda *args: True, lambda: provider).for_run('r')
    reserve = Mock(wraps=repo.reserve_call)
    invoke = TrackedLLMInvoker(scoped, reserve, repo.complete_call, request_options=research_model_options,
                               run_record_fn=repo.require_run, experiment_max_input_bytes=32000)
    crash = [provider_result == 'checkpoint_crash']
    def checkpoint(v):
        if v['status'] == 'response_received' and crash[0]:
            crash[0] = False
            raise RuntimeError('Simulated crash after settled response, before proposal checkpoint')
        repo.update_run('r', lambda r:{**r, 'state':{**r['state'], 'sharedExperimentGeneration':deepcopy(v)}})
    def run():
        return prepare(repo.require_run('r'), data, aliases,
            invoke=lambda node,prompt,opts:invoke('r',node,prompt,opts,use_reserve=True), checkpoint=checkpoint)
    if provider_result == 'timeout':
        with pytest.raises(LLMProviderError): run()
        assert repo.list_calls('r')[0]['status'] == 'unknown'
        with pytest.raises(DeepResearchError): run()
        assert post.call_count == 1 and len(repo.list_calls('r')) == 1
        return
    if provider_result == 'checkpoint_crash':
        with pytest.raises(RuntimeError): run()
        assert post.call_count == 1 and repo.list_calls('r')[0]['settled'] == 1
        assert repo.require_run('r')['state']['sharedExperimentGeneration']['status'] == 'pending'
    result = run()
    assert result['status'] == 'awaiting_scientific_review' and result['scientificApproval'] is False
    assert run() == result and post.call_count == 1
    assert repo.list_calls('r')[0]['argsDigest'] == digest(result['request'])
    wire = post.call_args.kwargs['json']
    assert post.call_args.args[0].endswith('/responses') and wire['text']['format'] == descriptor()
    assert wire['max_output_tokens'] == 6144 and wire['reasoning']['effort'] == 'none'
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == result['inputBytes']+1024+6144
    assert invoke.prompt_byte_limit('r',NODE) == 32000
    reserve.reset_mock()
    overlarge = 'x' * (32001-overhead_bytes(repo.require_run('r'), NODE))
    with pytest.raises(ValueError, match='Prompt too large'):
        invoke('r', NODE, overlarge, {'max_tokens':6144, 'temperature':0.0, 'timeout_seconds':90}, use_reserve=True)
    reserve.assert_not_called()
    assert post.call_count == 1
