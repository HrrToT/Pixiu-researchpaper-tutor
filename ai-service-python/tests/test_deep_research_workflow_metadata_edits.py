"""Explicit editing preserves unedited scientific choices; never quality credit."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.deep_research import workflow_metadata_edits as edits
from services.deep_research.contracts import digest,DeepResearchError
from services.deep_research.execution_workflow_blueprint import packed
from services.deep_research.workflow_metadata_symbols import decode,field_feedback
from services.deep_research.workflow_metadata_repair import prepare
from services.deep_research.workflow_units import unit_errors,META
from services.deep_research.experiment_planning import request_identity
from services.deep_research.planning_transport import dispatch_options,overhead_bytes,validate_options
from test_deep_research_workflow_revision_input import record as previous


def record():return {**previous(),'workflowRevisionReasoningContractVersion':0,'workflowMetadataEditsContractVersion':1}


def fixture():
    data=json.loads((Path(__file__).parent/'fixtures/dr_metadata_group_reads_20261115.json').read_text(encoding='utf8'))
    assert data['scientificApproval'] is False
    w=data['wire'];aliases={k:k for k in w['sourceRefs']};feedback=field_feedback(w,aliases)
    assert feedback['codes']==['timeline.input.group_leak']
    scope=edits.scope_for(record(),w,feedback)
    return w,aliases,feedback,scope


def patch(w):
    return {'baseDigest':digest(w),'edits':[{'op':'remove','path':f'/steps/4/reads/{i}'} for i in (2,3,4,5)],'unresolved':[]}


def failed(w,aliases):
    response={'content':packed(w),'rawContent':packed(w),'finishReason':'stop'}
    return {'status':'invalid_response','request':{'prompt':'original full metadata'},'response':response,
      'responseDigest':digest(response),'value':decode(w),'valueDigest':digest(decode(w)),
      'errors':unit_errors(decode(w),aliases,node=META,version=7,metadata_rows=True)}


def setup(response=None,r=None):
    w,aliases,feedback,scope=fixture();r=r or record();u=failed(w,aliases);saved=[]
    response=response or {'content':packed(patch(w)),'finishReason':'stop'}
    invoke=Mock(return_value=response)
    def run():return prepare(r,source_data=packed({'question':'Complete four-arm engineering fixture, unexecuted'}),
       failed=u,aliases=aliases,existing=saved[-1] if saved else None,invoke=invoke,checkpoint=lambda v:saved.append(deepcopy(v)))
    return r,w,u,invoke,saved,run


@pytest.mark.parametrize('marker',[None,True,False,0,2,'1'])
def test_strict_server_profile(marker):
    assert edits.enabled({**record(),'workflowMetadataEditsContractVersion':marker}) is (type(marker) is int and marker==2)


@pytest.mark.parametrize('key',['workflowRevisionInputContractVersion','workflowMetadataEnvelopeContractVersion',
 'workflowMetadataOutputContractVersion','workflowMetadataRepairContractVersion','executionWorkflowContractVersion','structuredOutputContractVersion'])
def test_incomplete_profiles_cannot_get_edit_mode(key):
    assert not edits.enabled({**record(),key:0})


def test_reasoning_trial_profile_cannot_silently_change_to_editing():
    assert not edits.enabled({**record(),'workflowRevisionReasoningContractVersion':1})


def test_legacy_edit_request_identity_is_frozen_after_new_guidance():
    _,_,_,_,saved,run=setup();run()
    assert digest(saved[-1]['request'])=='3bd456ee314ccce2faf2d4bd1400ca4ee22678abac1eb784df3d248dbac896db'


def test_new_guidance_changes_only_new_policy_and_scope_identity():
    r=record();r['workflowMetadataEditsContractVersion']=2
    _,w,_,invoke,saved,run=setup(r=r);run();s=saved[-1]
    assert s['editScope']['version']==2 and s['status']=='ready' and invoke.call_count==1
    assert 'NOT additional requirements' in s['request']['prompt']
    assert s['compiledWire']['sourceRefs']==w['sourceRefs']
    assert s['request']['extra']['max_tokens']==6144 and s['request']['extra']['timeout_seconds']==90
    assert s['scientificApproval'] is False


def test_explicit_simultaneous_edits_preserve_source_refs_and_every_other_field():
    w,aliases,_,scope=fixture();before=deepcopy(w);result=edits.apply(w,patch(w),scope)
    assert w==before and result['sourceRefs']==w['sourceRefs']
    assert {k:v for k,v in result.items() if k!='steps'}=={k:v for k,v in w.items() if k!='steps'}
    assert all(result['steps'][i]==w['steps'][i] for i in range(len(w['steps'])) if i!=4)
    assert {k:v for k,v in result['steps'][4].items() if k!='reads'}=={k:v for k,v in w['steps'][4].items() if k!='reads'}
    assert result['steps'][4]['reads']==w['steps'][4]['reads'][:2]
    assert {s['group'] for s in result['steps'] if s['kind']=='observe'}=={'00','01','10','11'}
    assert unit_errors(decode(result),aliases,node=META,version=7,metadata_rows=True)==[]


def test_replace_and_remove_address_original_indices_without_redirecting():
    w,_,_,scope=fixture();p=patch(w)
    p['edits'][0]={'op':'replace','path':'/steps/4/reads/2','value':{'state':'shared_base_3dgs','selector':'raw_sh'}}
    out=edits.apply(w,p,scope)
    assert out['steps'][4]['reads']==w['steps'][4]['reads'][:2]+[p['edits'][0]['value']]


@pytest.mark.parametrize('case',['base','foreign','duplicate','operation','fields','read','empty_selector','noop','empty','unresolved','unresolved_type','leading_zero'])
def test_invalid_or_out_of_scope_edits_are_rejected_without_mutation(case):
    w,_,_,scope=fixture();before=deepcopy(w);p=patch(w)
    if case=='base':p['baseDigest']='0'*64
    elif case=='foreign':p['edits'][0]['path']='/sourceRefs/0'
    elif case=='duplicate':p['edits'].append(deepcopy(p['edits'][0]))
    elif case=='operation':p['edits'][0]['op']='add'
    elif case=='fields':p['edits'][0]['value']={}
    elif case in ('read','empty_selector','noop'):
        p['edits'][0]={'op':'replace','path':'/steps/4/reads/2','value':
           {} if case=='read' else {'state':'shared_base_3dgs','selector':''} if case=='empty_selector' else deepcopy(w['steps'][4]['reads'][2])}
    elif case=='empty':p['edits']=[]
    elif case=='unresolved':p['unresolved']=['missing prerequisite']
    elif case=='unresolved_type':p['unresolved']=[False]
    else:p['edits'][0]['path']='/steps/04/reads/2'
    with pytest.raises(edits.EditError):edits.apply(w,p,scope)
    assert w==before


def test_one_repair_cached_replay_and_separate_raw_patch_and_compiled_value():
    _,w,u,invoke,saved,run=setup();before=deepcopy(u)
    a=run();b=run();s=saved[-1]
    assert a==b and invoke.call_count==1 and u==before
    assert s['status']=='ready' and s['scientificApproval'] is False
    assert s['response']['content']==packed(patch(w))
    assert s['compiledWire']!=patch(w) and s['value']==decode(s['compiledWire'])
    assert s['compiledWireDigest']==digest(s['compiledWire']) and s['editScope']['baseDigest']==digest(w)
    assert s['request']['extra'][edits.OPTION] is True
    assert s['request']['extra']['response_format']['name']=='metadata_explicit_read_edits_v1'
    assert 'fieldFeedback' in s['request']['prompt'] and '/steps/4/reads/2' in s['request']['prompt']


@pytest.mark.parametrize('kind',['scope','scope_digest','compiled','compiled_digest','response','value'])
def test_tampering_cannot_reuse_or_resend_a_saved_revision(kind):
    _,_,_,invoke,saved,run=setup();run();s=saved[-1]
    if kind=='scope':s['editScope']['paths']=[]
    elif kind=='scope_digest':s['editScopeDigest']='wrong'
    elif kind=='compiled':s['compiledWire']['sourceRefs']=[]
    elif kind=='compiled_digest':s['compiledWireDigest']='wrong'
    elif kind=='response':s['response']['content']='{}'
    else:s['value']['sourceRefs']=[]
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_blueprint_state' and invoke.call_count==1


@pytest.mark.parametrize('kind',['partial','foreign_state','truncated','malformed','unresolved','full_object','oversize','duplicate_keys'])
def test_invalid_edits_never_get_a_second_full_rewrite(kind):
    w,_,_,_=fixture();p=patch(w);finish='stop'
    if kind=='partial':p['edits']=p['edits'][:1]
    elif kind=='foreign_state':p['edits'][0]={'op':'replace','path':'/steps/4/reads/2','value':{'state':'foreign','selector':'x'}}
    elif kind=='truncated':finish='length'
    elif kind=='unresolved':p['unresolved']=['cannot resolve']
    elif kind=='full_object':p=w
    elif kind=='oversize':p['edits'][0]={'op':'replace','path':'/steps/4/reads/2','value':{'state':'shared_base_3dgs','selector':'x'*33000}}
    raw='{' if kind=='malformed' else packed(p)
    if kind=='duplicate_keys':raw=raw[:-1]+',"baseDigest":"'+digest(w)+'"}'
    _,_,_,invoke,saved,run=setup({'content':raw,'finishReason':finish})
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==1 and saved[-1]['status']=='invalid_response'
    if kind=='partial':assert 'timeline.input.group_leak' in saved[-1]['errors']
    if kind=='truncated':assert saved[-1]['errors']==['unit.output_truncated']
    if kind=='oversize':assert 'unit.output_capacity' in saved[-1]['errors']


def test_other_error_classes_keep_exact_full_revision_route():
    from test_deep_research_metadata_envelope import wire
    from services.deep_research.workflow_metadata_repair import prompt_for
    from services.deep_research.workflow_metadata_envelope import GUIDANCE
    w=wire();aliases={k:k for k in w['sourceRefs']};u=failed(w,aliases);r=record();saved=[]
    feedback={**field_feedback(w,aliases),'codes':sorted(u['errors'])}
    assert edits.scope_for(r,w,feedback) is None
    response={'content':packed(w),'finishReason':'stop'}
    with pytest.raises(DeepResearchError):
        prepare(r,source_data='{}',failed=u,aliases=aliases,existing=None,invoke=Mock(return_value=response),checkpoint=saved.append)
    assert saved[0]['request']==request_identity(r,edits.NODE,GUIDANCE+prompt_for('{}',w,feedback,version=34),{'temperature':0.0})
    assert 'editScope' not in saved[-1]


@pytest.mark.parametrize('size,allowed',[(40000,True),(40001,False)])
def test_edit_schema_input_cap_uses_actual_transport_before_dispatch(size,allowed):
    from services.deep_research.workflow_metadata_envelope import GUIDANCE
    r=record();w,aliases,feedback,scope=fixture();u=failed(w,aliases)
    def request(question):
        source=packed({'question':question})
        body=GUIDANCE+edits.prompt_for(source,w,feedback,scope)
        return source,request_identity(r,edits.NODE,body,{'temperature':0.0,edits.OPTION:True})
    _,base=request('');n=len(base['prompt'].encode())+overhead_bytes(r,edits.NODE,base['extra'])
    source,req=request('q'*(size-n))
    assert len(req['prompt'].encode())+overhead_bytes(r,edits.NODE,req['extra'])==size
    invoke=Mock(return_value={'content':packed(patch(w)),'finishReason':'stop'});saved=[]
    args=dict(source_data=source,failed=u,aliases=aliases,existing=None,invoke=invoke,checkpoint=saved.append)
    if allowed:prepare(r,**args)
    else:
        with pytest.raises(DeepResearchError) as e:prepare(r,**args)
        assert e.value.code=='workflow_blueprint_input_capacity'
        assert saved[-1]['inputBytes']==40001 and saved[-1]['maxInputBytes']==40000
    assert invoke.call_count==int(allowed)


def test_ready_patch_reopens_from_sqlite_without_a_second_provider_call(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();r=record();r.update(runId='r',taskId='t');repo.create_run(r)
    w,aliases,_,_=fixture();u=failed(w,aliases);source=packed({'question':'Complete four-arm fixture'})
    invoke=Mock(return_value={'content':packed(patch(w)),'finishReason':'stop'})
    def checkpoint(value):
        repo.update_run('r',lambda old:{**old,'state':{**old['state'],'executionWorkflowBlueprint':{'metadataRepair':value}}})
    a=prepare(repo.require_run('r'),source_data=source,failed=u,aliases=aliases,existing=None,invoke=invoke,checkpoint=checkpoint)
    fresh=DeepResearchRepository(tmp_path/'r.sqlite3');fresh.initialize();stored=fresh.require_run('r');no_send=Mock()
    b=prepare(stored,source_data=source,failed=u,aliases=aliases,
        existing=stored['state']['executionWorkflowBlueprint']['metadataRepair'],invoke=no_send,checkpoint=Mock())
    assert a==b and invoke.call_count==1
    no_send.assert_not_called()


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_native_edit_payload_reservation_and_no_unknown_retry(tmp_path,monkeypatch,scenario):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import BudgetExhaustedError,UnknownCallError,UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    from test_deep_research_schema_transport import response
    r=record();r.update(runId='r',taskId='t');repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    w,_,_,_=fixture();reply=packed(patch(w))
    post=Mock(side_effect=requests.ReadTimeout('unknown')) if scenario=='unknown' else Mock(return_value=response(reply))
    monkeypatch.setattr('llm.client.requests.post',post)
    client=ScopedModelClient(repo,lambda *a:True,lambda:DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')).for_run('r')
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000)) if scenario=='budget' else Mock(wraps=repo.reserve_call)
    invoke=TrackedLLMInvoker(client,reserve,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000,workflow_revision_max_input_bytes=40000)
    req=request_identity(r,edits.NODE,'Complete original input and explicit edit scope',{'temperature':0.0,edits.OPTION:True})
    def run():return invoke('r',edits.NODE,req['prompt'],dispatch_options(r,edits.NODE,req['extra']),use_reserve=True)
    if scenario=='budget':
        with pytest.raises(BudgetExhaustedError):run()
        post.assert_not_called();return
    if scenario=='unknown':
        with pytest.raises(LLMProviderError):run()
        with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    else:
        result=run();assert result['content']==reply and result['usage']['total_tokens']==16
    assert post.call_count==1 and repo.list_calls('r')[0]['argsDigest']==digest(req)
    payload=post.call_args.kwargs['json']
    assert payload['text']['format']['name']=='metadata_explicit_read_edits_v1'
    assert edits.OPTION not in payload and payload['reasoning']=={'effort':'none'}
    assert payload['max_output_tokens']==6144 and post.call_args.kwargs['timeout']==90
    overhead=overhead_bytes(r,edits.NODE,req['extra'])
    assert overhead<overhead_bytes(r,edits.NODE)
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(req['prompt'].encode())+1024+overhead+6144


@pytest.mark.parametrize('node,option',[('plan_workflow_meta',True),(edits.NODE,False),(edits.NODE,1)])
def test_edit_option_cannot_be_injected_into_other_roles_or_types(node,option):
    with pytest.raises(ValueError):request_identity(record(),node,'x',{edits.OPTION:option})
    with pytest.raises(ValueError):request_identity(previous(),edits.NODE,'x',{edits.OPTION:True})


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_server_marker_is_immutable_and_old_runs_cannot_opt_in(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
          'workflowMetadataEditsContractVersion':replacement},start_async=False)
        assert edits.enabled(r)
        assert r['workflowMetadataEditsContractVersion']==2
        # Historical version1 stays immutable while the server issues version2.
        r={**r,'runId':'historical-edits-v1','idempotencyKey':'historical-edits-v1','workflowMetadataEditsContractVersion':1}
        repo.create_run(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowMetadataEditsContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('workflowMetadataEditsContractVersion');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowMetadataEditsContractVersion':1})
    finally:facade.shutdown()
