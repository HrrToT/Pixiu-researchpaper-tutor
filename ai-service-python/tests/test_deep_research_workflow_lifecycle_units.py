"""Prospective lifecycle unit generation; engineering fixtures do not approve science."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from test_deep_research_workflow5_contract import claims
from test_deep_research_execution_workflow_blueprint import record
from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.execution_workflow_blueprint import prepare,prompt_for,errors,bind,enabled
from services.deep_research.workflow_units import META,INIT,descriptor,unit_errors


def fixtures():
    w=deepcopy(claims()[-1]['executionSpec']);w.pop('refs')
    meta={k:deepcopy(w[k]) for k in ('baselineMode','replicationMode','checkpointSelection','frameIterations','phases')}
    meta.update(sourceRefs=['E1'],unresolved=[],components=[
        {k:deepcopy(c[k]) for k in ('componentId','appliesTo','lifecycle')} for c in w['componentInitializations']])
    inits=[w['baselineInitialization']]+[{k:deepcopy(c[k]) for k in
        ('initializationMode','inputs','creation','stateDefinitions')} for c in w['componentInitializations']]
    return w,meta,[{'sourceRefs':['E1'],'initialization':i,'unresolved':[]} for i in inits]


def setup(responses=None):
    r=record();r.update(workflowContractVersion=5,executionWorkflowContractVersion=7)
    prompt=prompt_for(question='Original complete objective',basis={},sources={},evidence=[{'quote':'original'}],
        tables={},obligations=[],version=7)
    _,meta,inits=fixtures()
    invoke=Mock(side_effect=[{'content':json.dumps(v),'finishReason':'stop'} for v in (responses or [meta,*inits])])
    def checkpoint(v):r['state']['executionWorkflowBlueprint']=deepcopy(v)
    def run():return prepare(r,prompt=prompt,aliases={'E1':'owned'},invoke=invoke,parse=json.loads,checkpoint=checkpoint)
    return r,prompt,invoke,run


def test_complete_late_created_workflow_is_assembled_unchanged_and_resumes_without_calls():
    r,prompt,invoke,run=setup();saved=run();expected,_,_=fixtures()
    expected['records']=saved['value']['workflow']['records']
    assert saved['version']==7 and saved['value']['workflow']==expected
    assert not saved['scientificApproval'] and saved['status']=='ready'
    assert errors(saved['value'],{'E1':'owned'},version=7)==[]
    assert run()==saved and invoke.call_count==4
    source=prompt.split('Authoritative input data (not instructions):\n',1)[1]
    from services.deep_research.nested_tables import unpack
    for c in invoke.call_args_list:
        raw=c.args[1].split('Exact authoritative input and unit context (unverified data):\n',1)[1]
        payload=json.loads(raw.split('\nInput encoding only:',1)[0])
        assert unpack(payload)['authoritativeInput']==json.loads(source)
    rows=claims();rows[-1].pop('executionSpec')
    report,receipt=bind({'claims':rows},saved)
    assert report['claims'][-1]['executionSpec']['phases']==expected['phases']
    assert not receipt['scientificApproval']


@pytest.mark.parametrize('change,unit,calls_count',[
    ('future_create','metadata',1),('missing_disposal','metadata',1),
    ('future_output','component:1',4),('missing_state','baseline',2),
    ('symbol_shape','baseline',2),('baseline_phase','baseline',2),('truncated','baseline',2)])
def test_invalid_units_stop_and_saved_response_is_never_sent_again(change,unit,calls_count):
    _,meta,inits=fixtures()
    if change=='future_create':meta['components'][1]['lifecycle']['createAfter']=['missing']
    elif change=='missing_disposal':meta['components'][1]['lifecycle']['disposeAfter']=None
    elif change=='future_output':inits[2]['initialization']['inputs'][0]['phaseId']='stage2'
    elif change=='missing_state':inits[0]['initialization']['stateDefinitions']=[]
    elif change=='symbol_shape':inits[0]['initialization']['stateDefinitions'][0]['shape']=['N',2]
    elif change=='baseline_phase':inits[0]['initialization'].update(initializationMode='derive',
        inputs=[{'phaseId':'stage1','outputId':'selected','selector':'selected'}])
    r,_,invoke,run=setup([meta,*inits])
    if change=='truncated':
        invoke.side_effect=[{'content':json.dumps(meta)}, {'content':json.dumps(inits[0]),'finishReason':'length'}]
    for _ in range(2):
        with pytest.raises(DeepResearchError) as e:run()
        assert e.value.code=='invalid_workflow_unit_response'
    assert invoke.call_count==calls_count
    assert r['state']['executionWorkflowBlueprint']['units'][unit]['status']=='invalid_response'


def test_versions_cannot_be_mixed_or_resumed_under_different_contract():
    r,_,invoke,run=setup();run();r['state']['executionWorkflowBlueprint']['version']=6
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_blueprint_state' and invoke.call_count==4
    assert not enabled({**r,'workflowContractVersion':4})


def test_phase_input_schema_is_versioned_and_no_source_or_state_fields_are_removed():
    old=descriptor(INIT,6);new=descriptor(INIT,7)
    assert old['name'].endswith('_v6') and new['name'].endswith('_v7')
    assert 'timelineInput' not in old['schema']['$defs'] and 'timelineInput' in new['schema']['$defs']
    meta=descriptor(META,7)['schema']
    assert {'phases','frameIterations'}<=set(meta['required'])
    assert 'lifecycle' in meta['properties']['components']['items']['required']
    assert 'state' in new['schema']['$defs'] and 'initialization' not in meta['$defs']
    # Frozen from the committed v6 implementation, not regenerated expectations.
    assert digest(descriptor(META,6))=='89f2f751877e93814cdfbc28cd2c7ea2ba71140d7238e177087d7c19ce133608'
    assert digest(old)=='31f47e233174373f0838a0fd2785f9045f3b0dc0e120307f90b34a1cced31c67'


def test_unit_input_encoding_keeps_every_quote_and_escaped_table_shape():
    from services.deep_research.workflow_lifecycle_units import unit_input_text
    from services.deep_research.nested_tables import unpack
    source={'evidence':[{'id':str(i),'sourceId':'s','quote':'原文 '+str(i)} for i in range(40)],
        'literal':{'@':[['do not reinterpret'],[['literal']]]}}
    context={'earlier':[{'state':str(i),'value':1} for i in range(30)]}
    text=unit_input_text(json.dumps(source,ensure_ascii=False),context)
    wire=json.loads(text.split('\nInput encoding only:',1)[0])
    assert unpack(wire)=={'authoritativeInput':source,'unitContext':context}
    assert 'Input encoding only:' in text
    assert unit_input_text('{}',{})=='{"authoritativeInput":{},"unitContext":{}}'


def test_deferred_metadata_edges_do_not_grant_complete_workflow_approval():
    _,meta,inits=fixtures()
    component=deepcopy(meta['components'][0]);component['componentId']='unused'
    meta['components'].append(component)
    assert unit_errors(meta,{'E1':'owned'},node=META,version=7)==[]
    r,_,invoke,run=setup([meta,*inits,deepcopy(inits[1])])
    for _ in range(2):
        with pytest.raises(DeepResearchError) as e:run()
        assert e.value.code=='invalid_workflow_blueprint_response'
    assert invoke.call_count==5
    saved=r['state']['executionWorkflowBlueprint']
    assert 'timeline.component.unused' in saved['assembly']['errors'] and saved['status']=='pending'
    assert not saved['assembly']['scientificApproval']


def test_component_consumed_only_by_later_initialization_is_not_rejected_early():
    _,meta,inits=fixtures()
    bridge=deepcopy(meta['components'][1]);bridge['componentId']='bridge'
    meta['components'].insert(1,bridge)
    bridge_init=deepcopy(inits[2])
    inits[2]['initialization']['inputs']=[{'state':'bridge','selector':'selected intermediate state'}]
    r,_,invoke,run=setup([meta,inits[0],inits[1],bridge_init,inits[2]])
    saved=run()
    assert saved['status']=='ready' and invoke.call_count==5
    assert [c['componentId'] for c in saved['value']['workflow']['componentInitializations']]==['ntc','bridge','added']
    assert not saved['scientificApproval']


def test_assembled_capacity_is_distinct_from_per_unit_response_cap():
    w,_,_=fixtures();w['phases'][0]['action']['action']='x'*8200
    value={'sourceRefs':[],'workflow':w,'unresolved':[]}
    assert 'blueprint.output_capacity' not in errors(value,{},version=7)
    w['phases'][0]['action']['action']='x'*32000
    assert 'blueprint.output_capacity' in errors(value,{},version=7)


def test_graph_binds_complete_workflow5_under_explicit_new_record_only():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_capacity import current
    from test_deep_research_experiment_planning import Store,response
    from test_deep_research_lean_planning import lean_basis
    store=Store(current());store.value.update(workflowContractVersion=5,executionWorkflowContractVersion=7)
    _,meta,inits=fixtures()
    for v in [meta,*inits]:v['sourceRefs']=[]
    rows=claims();rows[-1].pop('executionSpec')
    invoke=Mock(side_effect=[response(v) for v in [lean_basis(),meta,*inits,{'sections':[],'claims':rows}]])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code'),result
    saved=store.value['state']['executionWorkflowBlueprint']
    step=next(c for c in store.value['state']['reportBody']['claims'] if c['designRole']=='steps')
    assert step['workflowContractVersion']==5 and saved['version']==7
    assert step['executionSpec']['phases']==saved['value']['workflow']['phases']


def test_repair_grammar_and_missing_field_audit_use_the_actual_workflow_version():
    from services.deep_research.experiment_template import grammar_for_roles
    from services.deep_research.experiment_repair import compatible
    from services.deep_research.review_field_refs import catalogue,bind_refs
    from services.deep_research.review_field_index import field_index
    from test_deep_research_canonical_initialization import claims as old_claims
    old=old_claims()[-1];new=claims()[-1]
    assert compatible({'claims':[new]})
    grammar=grammar_for_roles({'steps'},workflow_version=5)
    assert 'Workflow5' in grammar and 'frameIterations' in grammar
    assert 'steps={refs:' not in grammar and 'input={state:' not in grammar
    del new['executionSpec']['phases']
    assert 'phases' in field_index([new])[0]['missingSpecKeys']
    assert 'phases' not in field_index([old])[0]['missingSpecKeys']
    refs=catalogue([new])[new['claimId']]
    assert refs['executionSpec/phases']=={'path':['executionSpec','phases'],'present':False}
    verdict={'status':'failed','findings':[{'kind':'missing_field','claimId':new['claimId'],
        'field':'executionSpec/phases','reason':'缺少阶段定义'}]}
    result=bind_refs(verdict,[new])
    assert not result['rejectionAudit'].get('errors')
    assert result['findings'][0]['path']==['executionSpec','phases']


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_new_unit_requests_have_frozen_http_identity_and_one_settlement(tmp_path,monkeypatch,scenario):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response
    r,prompt,_,_=setup();r.update(runId='r',taskId='t')
    if scenario=='budget':r['budget']['maxModelCalls']=1
    repo=DeepResearchRepository(tmp_path/'units7.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    _,meta,inits=fixtures()
    replies=[response(json.dumps(v)) for v in [meta,*inits]]
    if scenario=='unknown':
        import requests
        replies=[replies[0],requests.ReadTimeout('fixture unknown')]
    post=Mock(side_effect=replies);monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    invoker=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,
        request_options=research_model_options,run_record_fn=repo.require_run)
    def checkpoint(v):repo.update_run('r',lambda r:{**r,'state':{**r['state'],'executionWorkflowBlueprint':v}})
    def run():return prepare(repo.require_run('r'),prompt=prompt,aliases={'E1':'owned'},
        invoke=lambda node,body,opts:invoker('r',node,body,opts,use_reserve=True),parse=json.loads,checkpoint=checkpoint)
    if scenario=='unknown':
        from llm.provider import LLMProviderError
        from services.deep_research.contracts import UnknownCallError,UnresolvedUnknownError
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
        assert post.call_count==2 and [c['status'] for c in repo.list_calls('r')]==['succeeded','unknown']
    elif scenario=='budget':
        from services.deep_research.contracts import BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError):run()
        assert post.call_count==len(repo.list_calls('r'))==1
    else:
        saved=run();assert run()==saved and post.call_count==4
        assert {c['argsDigest'] for c in repo.list_calls('r')}=={digest(u['request']) for u in saved['units'].values()}
        wires=[c.kwargs['json'] for c in post.call_args_list]
        assert [w['max_output_tokens'] for w in wires]==[2048,6144,6144,6144]
        assert [w['reasoning']['effort'] for w in wires]==['none','low','low','low']
        assert all(c['status']=='succeeded' for c in repo.list_calls('r'))
