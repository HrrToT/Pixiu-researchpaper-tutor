"""Unit source selection changes capacity, never source facts or review verdicts."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_premises import allocate,enabled
from test_deep_research_experiment_stage_allocation import current as stage_record


def record():
    r=stage_record();r['workflowPremiseAllocationContractVersion']=1
    r['state']['synthesisPremiseAllocation']={'requiredPremiseEvidenceAliases':['E1']}
    return r


def data():
    return {'question':'Full 2x2 request, not shortened','requirements':['all four arms and interaction'],
            'unverifiedScientificPlan':{'sourceRefs':['E2'],'protocol':{'state':'unchanged proposal'}},
            'sources':{'P1':'owned version'},'tables':{'T1':{'unmodified':[1,False,None]}},
            'evidence':[{'evidenceId':'E1','quote':'Exact required operation','sourceContext':{'after':'exact condition'}},
                        {'evidenceId':'E2','quote':'Exact basis source'},
                        {'evidenceId':'E3','quote':'Optional whole passage '+'x'*29000}]}


def select(monkeypatch,r=None,values=(),content=None,context=None):
    monkeypatch.setattr('services.deep_research.planning_transport.overhead_bytes',lambda *_:6470)
    return allocate(r or record(),source_data=json.dumps(content or data()),
        context=context or {'allowedSourceRefs':['E1','E2','E3']},aliases={'E1':'a','E2':'b','E3':'c'},
        prior_values=values,node='plan_workflow_meta',render=lambda text,ctx:text+'\n'+json.dumps(ctx))


def test_oversize_request_removes_only_unreferenced_optional_whole_rows(monkeypatch):
    r=record();original=data();before=deepcopy((r,original))
    body,text,ctx,aliases,audit=select(monkeypatch,r,content=original)
    restored=json.loads(text)
    assert restored=={**original,'evidence':original['evidence'][:2]}
    assert ctx['allowedSourceRefs']==['E1','E2'] and aliases=={'E1':'a','E2':'b'}
    assert audit['requiredAliases']==['E1','E2'] and audit['suppliedAliases']==['E1','E2']
    assert audit['inputBytes']==len(body.encode())+6470<=32000
    assert not audit['sourceSelectionIsScientificApproval'] and (r,original)==before


def test_prior_proposal_reference_cannot_be_dropped_to_force_admission(monkeypatch):
    body,text,ctx,aliases,audit=select(monkeypatch,values=[{'sourceRefs':['E3'],'unchanged':'prior'}])
    assert json.loads(text)==data() and set(aliases)=={'E1','E2','E3'}
    assert audit['inputBytes']>audit['maxInputBytes']==32000
    assert set(audit['requiredAliases'])==set(audit['suppliedAliases'])


@pytest.mark.parametrize('problem',['required_missing','plan_missing','prior_missing','duplicate','foreign_id','permissions','no_dependencies'])
def test_missing_or_ambiguous_dependency_never_becomes_a_smaller_request(monkeypatch,problem):
    r=record();d=data();prior=[];ctx={'allowedSourceRefs':['E1','E2','E3']}
    if problem=='required_missing':r['state']['synthesisPremiseAllocation']['requiredPremiseEvidenceAliases']=['E99']
    elif problem=='plan_missing':d['unverifiedScientificPlan']['sourceRefs']=['E99']
    elif problem=='prior_missing':prior=[{'sourceRefs':['E99']}]
    elif problem=='duplicate':d['evidence'].append(deepcopy(d['evidence'][0]))
    elif problem=='foreign_id':d['evidence'][0]['evidenceId']='E99'
    elif problem=='permissions':ctx['allowedSourceRefs']=['E1','E99']
    else:r['state'].pop('synthesisPremiseAllocation')
    with pytest.raises(DeepResearchError) as e:select(monkeypatch,r,prior,d,ctx)
    assert e.value.code=='invalid_workflow_premise_state'


@pytest.mark.parametrize('version',[None,True,False,0,2,'1'])
def test_legacy_contract_cannot_be_implicitly_enabled(version):
    assert not enabled({**record(),'workflowPremiseAllocationContractVersion':version})


def workflow_setup(*,optional=False,all_required=False,reply_ref='E1'):
    from services.deep_research.execution_workflow_blueprint import prepare,prompt_for
    from test_deep_research_workflow_lifecycle_units import fixtures
    r=record();d=data()
    if not optional:d['evidence']=d['evidence'][:2]
    if all_required:r['state']['synthesisPremiseAllocation']['requiredPremiseEvidenceAliases'].append('E3')
    p=prompt_for(question=d['question'],basis=d['unverifiedScientificPlan'],sources=d['sources'],
        evidence=d['evidence'],tables=d['tables'],obligations=d['requirements'],version=7)
    _,meta,inits=fixtures()
    meta['sourceRefs']=[reply_ref]
    invoke=Mock(side_effect=[{'content':json.dumps(v),'finishReason':'stop'} for v in [meta,*inits]])
    def checkpoint(v):r['state']['executionWorkflowBlueprint']=deepcopy(v)
    aliases={'E1':'a','E2':'b',**({'E3':'c'} if optional else {})}
    def run():return prepare(r,prompt=p,aliases=aliases,invoke=invoke,parse=json.loads,checkpoint=checkpoint)
    return r,invoke,run


def test_all_units_bind_dependencies_and_completed_resume_sends_nothing():
    r,invoke,run=workflow_setup();saved=run();assert saved['status']=='ready'
    calls=invoke.call_count;assert calls==4
    for key,unit in saved['units'].items():
        a=unit['premiseAllocation'];assert set(a['requiredAliases'])=={'E1','E2'}
        assert len(a['priorProposalDigests'])==list(saved['units']).index(key)
        assert a['inputBytes']<=32000 and not a['sourceSelectionIsScientificApproval']
    assert run()==saved and invoke.call_count==calls


@pytest.mark.parametrize('tamper',['allocation','dependencies'])
def test_saved_request_and_allocation_cannot_be_rewritten(tamper):
    r,invoke,run=workflow_setup()
    run();count=invoke.call_count
    if tamper=='allocation':r['state']['executionWorkflowBlueprint']['units']['metadata']['premiseAllocation']['suppliedAliases']=[]
    else:r['state']['synthesisPremiseAllocation']['requiredPremiseEvidenceAliases']=[]
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


def test_complete_required_overflow_stops_without_provider_or_automatic_retry():
    r,invoke,run=workflow_setup(optional=True,all_required=True)
    for _ in range(2):
        with pytest.raises(DeepResearchError) as e:run()
        assert e.value.code=='workflow_blueprint_input_capacity'
    invoke.assert_not_called()
    unit=r['state']['executionWorkflowBlueprint']['units']['metadata']
    assert set(unit['premiseAllocation']['suppliedAliases'])=={'E1','E2','E3'}
    assert unit['status']=='not_started_capacity'


def test_reference_to_unsupplied_optional_source_is_not_approved():
    r,invoke,run=workflow_setup(optional=True,reply_ref='E3')
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_unit_response' and invoke.call_count==1
    unit=r['state']['executionWorkflowBlueprint']['units']['metadata']
    assert 'E3' not in unit['premiseAllocation']['suppliedAliases']
    assert 'unit.unsupplied_source_reference' in unit['errors']


def test_unknown_physical_request_is_not_resent_on_same_checkpoint(tmp_path,monkeypatch):
    import requests
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError,UnresolvedUnknownError
    from llm.client import DeepSeekLLM
    from llm.provider import LLMProviderError
    r,invoke,run=workflow_setup();r.update(runId='r',taskId='t',structuredOutputContractVersion=15)
    repo=DeepResearchRepository(tmp_path/'unknown.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    post=Mock(side_effect=requests.ReadTimeout('fixture unknown'))
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    tracked=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,
        request_options=research_model_options,run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    invoke.side_effect=lambda n,p,o:tracked('r',n,p,o,use_reserve=True)
    with pytest.raises(LLMProviderError):run()
    checkpoint=deepcopy(r['state']['executionWorkflowBlueprint'])
    with pytest.raises((UnknownCallError,UnresolvedUnknownError)):run()
    assert post.call_count==1 and r['state']['executionWorkflowBlueprint']==checkpoint


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_server_owns_immutable_allocation_marker(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design',
            'outputKind':'experiment_design','workflowPremiseAllocationContractVersion':replacement,'deferStart':True},start_async=False)
        assert r['workflowPremiseAllocationContractVersion']==1 and enabled(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowPremiseAllocationContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');del old['workflowPremiseAllocationContractVersion'];repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowPremiseAllocationContractVersion':1})
    finally:facade.shutdown()
