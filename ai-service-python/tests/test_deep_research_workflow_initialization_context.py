"""Scoped interfaces do not replace complete-context validation or evidence."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.workflow_initialization_context import enabled, project
from services.deep_research.workflow_units import unit_prompt, INIT
from services.deep_research.workflow_initialization_wire import bind_prompt, TARGET_OPTION
from services.deep_research.planning_transport import overhead_bytes
from services.deep_research.contracts import digest, DeepResearchError
from test_deep_research_workflow_metadata_window import record as premise_record
from test_deep_research_workflow_lifecycle_units import fixtures
from test_deep_research_workflow_metadata_ordered_integration import input_value
from test_deep_research_workflow_initialization_wire import to_wire


def record():
    return {**premise_record(), 'workflowInitializationOutputContractVersion': 1,
        'workflowInitializationRepairContractVersion': 2, 'workflowInitializationContextContractVersion': 1}


def context():
    _, meta, _ = fixtures()
    return {'target': 'baseline', 'metadata': meta, 'earlier': []}


@pytest.mark.parametrize('marker', [None, True, False, 0, 2, '1'])
def test_strict_marker_keeps_legacy_context(marker):
    assert not enabled({**record(), 'workflowInitializationContextContractVersion': marker})


@pytest.mark.parametrize('key', ['workflowInitializationRepairContractVersion', 'workflowInitializationOutputContractVersion',
    'executionWorkflowContractVersion', 'workflowPremiseAllocationContractVersion', 'experimentStageAllocationContractVersion'])
def test_partial_profiles_cannot_project_context(key):
    assert not enabled({**record(), key: 0})


def test_baseline_preserves_all_physical_choices_and_binds_original_metadata():
    ctx = context(); before = deepcopy(ctx); view = project(ctx)
    assert ctx == before and view['target'] == 'baseline' and view['earlier'] == []
    assert view['binding'] == {'metadataDigest': digest(ctx['metadata']), 'contextDigest': digest(ctx),
        'phaseCount': len(ctx['metadata']['phases'])}
    assert view['operationRequirements'] == [{k: p[k] for k in ('groups', 'action', 'budget')}
        for p in ctx['metadata']['phases'] if p['kind'] in ('setup', 'fit')]
    assert view['metadataHeader'] == {k: v for k, v in ctx['metadata'].items() if k not in ('phases', 'components')}
    assert 'phases' not in view and view['componentInterfaces'] == [{k: v for k, v in c.items() if k != 'lifecycle'} for c in ctx['metadata']['components']]


def test_input_retains_complete_question_quotes_and_prior_protocol_values():
    ctx = context(); data = {'question': 'all arms, no simplification', 'evidence': [{'quote': 'exact original'}],
        'unverifiedScientificPlan': {'state': 'chosen full-state shape'}, 'requirements': ['all requested metrics']}
    raw = unit_prompt(json.dumps(data), node=INIT, context=ctx, version=7, scoped_initialization_input=True)
    decoded = input_value(raw)
    assert decoded == {'authoritativeInput': data, 'unitContext': project(ctx)}
    assert 'not initialization actions' in raw


@pytest.mark.parametrize('mode,node,version', [(True, 'plan_workflow_meta', 7), (True, INIT, 6), (1, INIT, 7)])
def test_scoped_mode_cannot_modify_other_grammars(mode, node, version):
    with pytest.raises(ValueError): unit_prompt('{}', node=node, context=context(), version=version, scoped_initialization_input=mode)


def availability_context():
    phase = {'phaseId': 'p0', 'scope': 'per_repeat', 'kind': 'setup', 'groups': ['A', 'B'], 'sharing': 'per_group',
        'after': [], 'reads': [], 'updates': [], 'outputs': ['r0'], 'action': {'action': 'make', 'parameters': []}, 'budget': None}
    def component(name, groups, after, dispose=None, scope='per_repeat'):
        return {'componentId': name, 'appliesTo': groups, 'lifecycle': {'scope': scope, 'createAfter': after, 'disposeAfter': dispose}}
    components = [component('available', ['A', 'B'], []), component('other_group', ['B'], []),
        component('disposed', ['A', 'B'], [], 'p0'), component('target', ['A'], ['p0'])]
    metadata = {'baselineMode': 'train', 'replicationMode': 'clone', 'sourceRefs': ['E1'], 'checkpointSelection': None,
        'unresolved': [], 'frameIterations': 0, 'phases': [phase, {**deepcopy(phase), 'phaseId': 'future'}], 'components': components}
    earlier = [{**deepcopy(c), 'initializationMode': 'fresh', 'inputs': [], 'creation': {'action': 'make', 'parameters': []}, 'stateDefinitions': []}
               for c in components[:3]]
    return {'target': deepcopy(components[-1]), 'metadata': metadata, 'earlier': earlier, 'baselineInitialization': {'typedState': 'preserved'}}


def test_component_only_exposes_legal_prior_states_and_outputs_but_keeps_full_binding():
    ctx = availability_context(); before = deepcopy(ctx); view = project(ctx)
    assert ctx == before and [p['phaseId'] for p in view['availablePhases']] == ['p0']
    assert [p['componentId'] for p in view['earlier']] == ['available']
    assert view['earlier'][0] == ctx['earlier'][0] and view['baselineInitialization'] == ctx['baselineInitialization']
    assert view['binding']['contextDigest'] == digest(ctx) and view['target'] == ctx['target']


def test_per_frame_state_is_not_available_to_per_repeat_initializer():
    ctx = availability_context(); ctx['metadata']['phases'][0]['scope'] = 'per_frame'
    ctx['metadata']['frameIterations'] = 1; ctx['target']['lifecycle']['createAfter'] = ['future']
    ctx['metadata']['components'][-1] = deepcopy(ctx['target'])
    view = project(ctx)
    assert all(p['scope'] == 'per_repeat' for p in view['availablePhases'])


@pytest.mark.parametrize('change', ['unknown_target', 'reordered_predecessors', 'unknown_context_field', 'baseline_earlier'])
def test_unrecognized_context_is_not_silently_projected(change):
    ctx = availability_context()
    if change == 'unknown_target': ctx['target']['componentId'] = 'missing'
    if change == 'reordered_predecessors': ctx['earlier'].reverse()
    if change == 'unknown_context_field': ctx['unknown'] = 'must not be discarded'
    if change == 'baseline_earlier': ctx['target'] = 'baseline'
    with pytest.raises((ValueError, KeyError)): project(ctx)


def test_target_specific_transport_size_is_exact_only_for_new_profile():
    from services.deep_research.workflow_initialization_wire import descriptor
    options = {TARGET_OPTION: 'baseline'}
    actual = len(json.dumps({'_deepseek_api': 'responses', 'response_format': descriptor('baseline')}, ensure_ascii=False, separators=(',', ':')).encode())
    assert overhead_bytes(record(), INIT, options) == actual
    old = record(); old.pop('workflowInitializationContextContractVersion')
    assert overhead_bytes(old, INIT, options) == overhead_bytes(old, INIT)


def setup():
    from test_deep_research_workflow_premises import workflow_setup
    r, invoke, run = workflow_setup()
    r.update(workflowInitializationOutputContractVersion=1, workflowInitializationRepairContractVersion=2,
        workflowInitializationContextContractVersion=1, structuredOutputContractVersion=15)
    _, meta, initializers = fixtures()
    invoke.side_effect = [{'content': json.dumps(v), 'finishReason': 'stop'} for v in [meta, *[to_wire(i) for i in initializers]]]
    return r, invoke, run


def test_complete_workflow_uses_full_metadata_for_validation_and_assembly():
    r, invoke, run = setup(); saved = run(); full, _, _ = fixtures()
    assert saved['status'] == 'ready' and saved['value']['workflow']['phases'] == full['phases']
    assert saved['value']['workflow']['componentInitializations'] == full['componentInitializations']
    for call in invoke.call_args_list:
        if call.args[0] == INIT:
            value = input_value(call.args[1]); assert 'metadataHeader' in value['unitContext']
            assert 'metadata' not in value['unitContext']
            assert value['authoritativeInput']['question'] == 'Full 2x2 request, not shortened'
    n = invoke.call_count; assert run() == saved and invoke.call_count == n


def test_projected_view_does_not_approve_a_future_input():
    r, invoke, run = setup(); calls = list(invoke.side_effect)
    bad = deepcopy(calls[-1]); value = json.loads(bad['content']); init = value['initialization']
    assert init['initializationMode'] == 'derive'
    init['input'] = {'phaseId': 'missing', 'outputId': 'r0', 'selector': 'all'}
    bad['content'] = json.dumps(value); calls[-1] = bad
    # The unique initialization repair is also rejected, without filling data.
    invoke.side_effect = calls + [bad]
    with pytest.raises(DeepResearchError): run()
    assert r['state']['executionWorkflowBlueprint']['units']['component:1']['status'] == 'invalid_response'
    repair=r['state']['executionWorkflowBlueprint']['initializationRepair']
    view=input_value(repair['request']['prompt'])['unitContext']
    assert 'metadataHeader' in view and 'metadata' not in view


def test_legacy_completed_workflow_cannot_be_reinterpreted_or_resent():
    from test_deep_research_workflow_premises import workflow_setup
    r, invoke, run=workflow_setup()
    r.update(workflowInitializationOutputContractVersion=1,workflowInitializationRepairContractVersion=2,
        structuredOutputContractVersion=15)
    _,meta,inits=fixtures();invoke.side_effect=[{'content':json.dumps(v),'finishReason':'stop'} for v in [meta,*[to_wire(i) for i in inits]]]
    run();n=invoke.call_count;r['workflowInitializationContextContractVersion']=1
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==n


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.planning_transport import dispatch_options
    from services.deep_research.experiment_planning import request_identity
    from services.deep_research.contracts import BudgetExhaustedError,UnknownCallError,UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r=record();r.update(runId='r',taskId='t');repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('unknown')) if scenario=='unknown' else Mock(return_value=response('{}'))
    monkeypatch.setattr('llm.client.requests.post',post)
    client=ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario=='budget' else Mock(wraps=repo.reserve_call)
    tracked=TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    req=request_identity(r,INIT,'x'*(32000-overhead_bytes(r,INIT,{TARGET_OPTION:'baseline'})),{TARGET_OPTION:'baseline'})
    def run():return tracked('r',INIT,req['prompt'],dispatch_options(r,INIT,req['extra']),use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    else:run()
    assert post.call_count==1 and repo.list_calls('r')[0]['argsDigest']==digest(req)
    actual=post.call_args.kwargs['json'];assert actual['text']['format']['name']=='workflow_init_v2_baseline'
    assert actual['max_output_tokens']==6144 and post.call_args.kwargs['timeout']==90
    assert reserve.call_args.kwargs['budget_delta']['tokens']==32000+1024+6144
    with pytest.raises(ValueError,match='Prompt too large'):
        tracked('r',INIT,req['prompt']+'x',dispatch_options(r,INIT,req['extra']),use_reserve=True)
    assert post.call_count==1


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_marker_is_server_owned_and_immutable(tmp_path, replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize(); f = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = f.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Design', 'deferStart': True,
            'workflowInitializationContextContractVersion': replacement}, start_async=False)
        assert r['workflowInitializationContextContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda old: {**old, 'workflowInitializationContextContractVersion': replacement})
        old = deepcopy(r); old.update(runId='old', idempotencyKey='old'); old.pop('workflowInitializationContextContractVersion'); repo.create_run(old)
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run('old', lambda x: {**x, 'workflowInitializationContextContractVersion': 1})
    finally: f.shutdown()
