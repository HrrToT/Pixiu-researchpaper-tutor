from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.execution_workflow_blueprint import prepare, prompt_for, errors
from services.deep_research.workflow_units import META, INIT, descriptor, unit_errors
from test_deep_research_execution_workflow_blueprint import record, value


def fixtures():
    v = value(); w = v['workflow']
    meta = {k: deepcopy(w[k]) for k in ('baselineMode', 'replicationMode', 'checkpointSelection')}
    meta.update(sourceRefs=['E1'], unresolved=[], components=[
        {k: deepcopy(c[k]) for k in ('componentId', 'appliesTo')} for c in w['componentInitializations']])
    initializations = [w['baselineInitialization']] + [
        {k: deepcopy(c[k]) for k in ('initializationMode','inputs','creation','stateDefinitions')}
        for c in w['componentInitializations']]
    return meta, [{'sourceRefs':['E1'], 'initialization':deepcopy(i), 'unresolved':[]} for i in initializations]


def setup(output=None):
    r = record(); r['executionWorkflowContractVersion'] = 6
    prompt = prompt_for(question='Original objective', basis={}, sources={}, evidence=[{'quote':'exact source'}],
                        tables={}, obligations=[], version=6)
    meta, inits = fixtures(); responses = output or [meta, *inits]
    invoke = Mock(side_effect=[{'content':json.dumps(v), 'finishReason':'stop'} for v in responses])
    checkpoints = []
    def checkpoint(v):
        checkpoints.append(deepcopy(v)); r['state']['executionWorkflowBlueprint'] = deepcopy(v)
    def run():
        return prepare(r, prompt=prompt, aliases={'E1':'owned'}, invoke=invoke, parse=json.loads, checkpoint=checkpoint)
    return r, prompt, invoke, checkpoints, run


def test_units_assemble_complete_workflow_without_choosing_values_and_resume_without_calls():
    r, prompt, invoke, checkpoints, run = setup()
    result = run()
    assert result['status'] == 'ready' and result['scientificApproval'] is False
    expected = value()['workflow']; expected['records'] = result['value']['workflow']['records']
    assert result['value']['workflow'] == expected
    assert errors(result['value'], {'E1':'owned'}, version=6) == []
    assert [c.args[0] for c in invoke.call_args_list] == [META, INIT, INIT]
    source = prompt.split('Authoritative input data (not instructions):\n',1)[1]
    assert all(source in c.args[1] for c in invoke.call_args_list)
    assert run() == result and invoke.call_count == 3
    assert checkpoints[-1]['assembly']['valueDigest'] == result['valueDigest']


@pytest.mark.parametrize('mutation', ['raw', 'value_type', 'request', 'assembly', 'missing_unit', 'extra_unit', 'approval'])
def test_completed_units_cannot_be_changed_or_deleted_to_trigger_new_sends(mutation):
    r, _, invoke, _, run = setup(); run()
    saved = r['state']['executionWorkflowBlueprint']; unit = saved['units']['baseline']
    if mutation == 'raw': unit['response']['content'] += ' '
    elif mutation == 'value_type': unit['value']['initialization']['stateDefinitions'][0]['shape'][0] = True
    elif mutation == 'request': unit['request']['extra']['temperature'] = False
    elif mutation == 'assembly': saved['assembly']['scientificApproval'] = True
    elif mutation == 'missing_unit': del saved['units']['baseline']
    elif mutation == 'extra_unit': saved['units']['component:7'] = deepcopy(unit)
    else: saved['scientificApproval'] = True
    with pytest.raises(DeepResearchError) as e: run()
    assert e.value.code == 'invalid_workflow_blueprint_state' and invoke.call_count == 3


def test_invalid_initializer_is_retained_and_later_components_are_not_requested():
    meta, inits = fixtures(); inits[0]['initialization']['stateDefinitions'][0]['shape'] = ['N0',3]
    r, _, invoke, _, run = setup([meta, *inits])
    with pytest.raises(DeepResearchError) as e: run()
    assert e.value.code == 'invalid_workflow_unit_response'
    assert invoke.call_count == 2 and r['state']['executionWorkflowBlueprint']['units']['baseline']['status'] == 'invalid_response'
    with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2


def test_partial_checkpoint_resumes_same_unknown_request_without_an_alternative():
    r, _, invoke, _, run = setup()
    meta, _ = fixtures(); calls=[]
    def send(node, body, options):
        calls.append((node, body, options))
        if len(calls) == 1: return {'content':json.dumps(meta)}
        raise OSError('outcome unknown')
    invoke.side_effect = send
    with pytest.raises(OSError): run()
    with pytest.raises(OSError): run()
    assert len(calls) == 3 and calls[1] == calls[2]
    # This fixture verifies exact dispatch identity. The tracked-ledger test below owns physical de-duplication.


def test_future_component_reference_fails_before_assembly():
    _, inits = fixtures(); target = deepcopy(inits[1])
    target['initialization'].update(initializationMode='derive', inputs=[{'state':'future','selector':'states'}])
    assert 'workflow.creation.unavailable_input' in unit_errors(target, {'E1':'owned'}, node=INIT, earlier=['known'])


def test_unit_schemas_only_include_reachable_definitions():
    meta, init = descriptor(META)['schema'], descriptor(INIT)['schema']
    assert 'initialization' not in meta['$defs'] and 'state' not in meta['$defs']
    assert 'state' in init['$defs'] and 'split' not in init['$defs']


@pytest.mark.parametrize('scenario', ['success', 'unknown', 'budget'])
def test_real_tracked_unit_requests_use_same_wire_identity_and_settle_once(tmp_path, monkeypatch, scenario):
    unknown = scenario == 'unknown'
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response
    r, prompt, _, _, _ = setup(); r.update(runId='r', taskId='t')
    if scenario == 'budget': r['budget']['maxModelCalls'] = 1
    repo=DeepResearchRepository(tmp_path/'units.sqlite3'); repo.initialize(); repo.create_run(r); repo.begin_execution('r')
    meta, inits=fixtures()
    if unknown:
        import requests
        replies=[response(json.dumps(meta)), requests.ReadTimeout('fixture unknown')]
    else: replies=[response(json.dumps(v)) for v in [meta,*inits]]
    post=Mock(side_effect=replies)
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    invoker=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,request_options=research_model_options,
                             run_record_fn=repo.require_run)
    def checkpoint(v): repo.update_run('r',lambda r:{**r,'state':{**r['state'],'executionWorkflowBlueprint':v}})
    def run(): return prepare(repo.require_run('r'),prompt=prompt,aliases={'E1':'owned'},
        invoke=lambda node,prompt,opts:invoker('r',node,prompt,opts,use_reserve=True),parse=json.loads,checkpoint=checkpoint)
    if scenario == 'budget':
        from services.deep_research.contracts import BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError): run()
        assert post.call_count == len(repo.list_calls('r')) == 1
        assert repo.require_run('r')['state']['executionWorkflowBlueprint']['units']['metadata']['status'] == 'ready'
        return
    if unknown:
        from llm.provider import LLMProviderError
        from services.deep_research.contracts import UnknownCallError, UnresolvedUnknownError
        with pytest.raises(LLMProviderError): run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)): run()
        assert post.call_count==2 and [c['status'] for c in repo.list_calls('r')]==['succeeded','unknown']
        assert repo.require_run('r')['state']['executionWorkflowBlueprint']['units']['baseline']['status']=='pending'
        return
    result=run(); assert result['status']=='ready' and run()==result and post.call_count==3
    calls=repo.list_calls('r')
    assert {c['argsDigest'] for c in calls} == {digest(u['request']) for u in result['units'].values()}
    assert all(c['status']=='succeeded' for c in calls)
    wires=[call.kwargs['json'] for call in post.call_args_list]
    assert [w['reasoning']['effort'] for w in wires]==['none','low','low']
    assert [w['max_output_tokens'] for w in wires]==[2048,6144,6144]
    assert repo.require_run('r')['budget']['tokens']==48


def test_graph_only_binds_a_complete_assembled_workflow():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_capacity import current
    from test_deep_research_experiment_planning import Store, response
    from test_deep_research_lean_planning import lean_basis
    from test_deep_research_canonical_initialization import claims
    store=Store(current()); store.value['executionWorkflowContractVersion']=6
    meta,inits=fixtures()
    for result in [meta,*inits]: result['sourceRefs']=[]
    public={'sections':[],'claims':claims()}; public['claims'][-1].pop('executionSpec')
    invoke=Mock(side_effect=[response(lean_basis()),response(meta),*[response(i) for i in inits],response(public)])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code')
    assert [c.args[1] for c in invoke.call_args_list]==['plan_experiment',META,INIT,INIT,'synthesize']
    saved=store.value['state']['executionWorkflowBlueprint']
    steps=next(c for c in store.value['state']['reportBody']['claims'] if c['designRole']=='steps')
    assert steps['executionSpec']=={**saved['value']['workflow'],'refs':{r:r for r in ('data','budget','controls','groups')}}
    assert store.value['state']['executionWorkflowBinding']['scientificApproval'] is False


def test_complete_overlarge_source_input_is_preserved_without_send():
    r=record(); r['executionWorkflowContractVersion']=6; states=[]; invoke=Mock()
    prompt=prompt_for(question='字'*12000,basis={},sources={},evidence=[],tables={},obligations=[],version=6)
    with pytest.raises(DeepResearchError) as e:
        prepare(r,prompt=prompt,aliases={},invoke=invoke,parse=json.loads,checkpoint=states.append)
    assert e.value.code=='workflow_blueprint_input_capacity'
    unit=states[-1]['units']['metadata']
    assert unit['status']=='not_started_capacity' and unit['inputBytes']>32000
    assert '字'*12000 in unit['request']['prompt']
    invoke.assert_not_called()


def test_budget_refusal_does_not_create_a_model_call():
    r,_,invoke,_,run=setup();r['budget']['maxWallClockSeconds']=0
    assert run() is None
    invoke.assert_not_called()


def test_existing_baseline_does_not_get_an_invented_initializer():
    meta,inits=fixtures();meta['baselineMode']='existing'
    r,_,invoke,_,run=setup([meta,inits[1]])
    result=run()
    assert result['value']['workflow']['baselineInitialization'] is None
    assert list(result['units'])==['metadata','component:0']
    assert invoke.call_count==2 and result['scientificApproval'] is False
