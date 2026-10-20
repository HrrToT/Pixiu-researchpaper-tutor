from copy import deepcopy
from datetime import datetime, UTC, timedelta
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.experiment_planning import (
    MAX_BASIS_BYTES, enabled, prepare_plan, prepare_draft, remaining_seconds,
    request_identity, validate_basis,
)
from services.deep_research.graph import make_synthesize_node
from services.deep_research.runtime import research_model_options
from test_deep_research_experiment_shared_grammar import record


def basis():
    return {'sourceFacts':[{'topic':'Operation','evidenceRefs':['E1'],'scope':'h = f(x, t + n)'}],
        'protocol':{'intervention':'Apply the supplied time perturbation only before f.',
            'data':'Proposed sorted first scene; split views by index modulo 5 before fitting.',
            'state':'Initialize all primitive states and a concrete MLP separately from training inputs.',
            'poseError':'Not applicable to this requested isolated intervention.',
            'measurement':'Use observed held-out references; compensate actual motion, retain a quality guard.',
            'pairingBudget':'One paired scene/seed, equal whole-group steps, descriptive effects only.'},
        'unresolved':[]}


def current():
    value=record();value['experimentDraftContractVersion']=3
    value['structuredOutputContractVersion']=7
    value['budget']={'maxWallClockSeconds':360,'elapsedSeconds':0}
    return value


def response(value=None):
    return {'content':json.dumps(basis() if value is None else value),'finishReason':'stop'}


class Store:
    def __init__(self,value=None):
        self.value=deepcopy(value or current());self.checkpoints=[]

    def checkpoint(self,value):
        self.checkpoints.append(deepcopy(value));self.value['state']['experimentPlanning']=deepcopy(value)

    def update(self,_id,change,**_kw):
        self.value=change(deepcopy(self.value));return deepcopy(self.value)


def prepare(store,invoke,prompt='original scientific question and exact source'):
    return prepare_plan(store.value,prompt=prompt,aliases={'E1':'eq'},
        invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)


def test_two_stage_graph_keeps_sources_and_complete_grammar_but_never_grants_plan_approval():
    store=Store();original=deepcopy(store.value['state']['evidence'])
    draft={'designBasis':{'echo':'PRIVATE ECHO'},'sections':[{'title':'指标','claimIds':['c']}],
        'claims':[{'claimId':'c','kind':'proposal','designRole':'metrics','text':'Proposed observable.',
            'evidenceRefs':[],'conditions':{},'obligationIds':['o']}]}
    invoke=Mock(side_effect=[response(),response(draft)])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert 'error_code' not in result
    assert [call.args[1] for call in invoke.call_args_list]==['plan_experiment','synthesize']
    planner,body=invoke.call_args_list
    for call in (planner,body):
        assert call.kwargs['use_reserve'] is True
        assert original[0]['quote'] in call.args[2]
        assert len(call.args[2].encode())<=24000
    assert 'Final evaluation views cannot choose checkpoints' in planner.args[2]
    assert 'stateDefinitions' in body.args[2] and 'group_checkpoints' in body.args[2]
    assert json.dumps(basis(),ensure_ascii=False,separators=(',',':')) in body.args[2]
    assert 'shared executionSpec' not in planner.args[2]
    actual_options=research_model_options('synthesize',body.args[3])
    assert actual_options['thinking']=={'type':'disabled'} and actual_options['max_tokens']==16384
    assert planner.args[3]['max_tokens']==6144 and planner.args[3]['reasoning_effort']=='low'
    saved=store.value['state']['experimentPlanning']
    assert saved['verification']=='unchecked' and saved['draftStatus']=='prepared'
    assert saved['draftRequest']==request_identity(store.value,'synthesize',body.args[2],body.args[3])
    public=store.value['state']['reportBody']
    assert 'designBasis' not in public and 'PRIVATE ECHO' not in json.dumps(public)
    assert public['claims'][0]['evidenceRefs']==[] and 'verification' not in public['claims'][0]
    assert store.value['state']['evidence']==original
    assert store.value['state']['experimentDraftingAudit']['verification']=='unchecked'


def test_plan_and_direct_body_are_frozen_and_reused_without_new_planning_call():
    store=Store();invoke=Mock(return_value=response())
    first=prepare(store,invoke)
    assert [s['status'] for s in store.checkpoints]==['pending','response_received','ready']
    again=prepare(store,invoke)
    assert first==again and invoke.call_count==1
    request=prepare_draft(store.value,again,prompt='full body source/config',checkpoint=store.checkpoint)
    # A late resume still reaches the tracked ledger to reuse or reject unknown.
    store.value['budget']['elapsedSeconds']=999
    assert prepare_draft(store.value,store.value['state']['experimentPlanning'],
        prompt='full body source/config',checkpoint=store.checkpoint)==request
    with pytest.raises(DeepResearchError,match='原输入'):
        prepare_draft(store.value,store.value['state']['experimentPlanning'],
            prompt='changed body',checkpoint=store.checkpoint)


@pytest.mark.parametrize('corruption',['basis','response','responseDigest','evidenceAliases','inputDigest','request','status'])
def test_corrupt_saved_plan_fails_without_sending(corruption):
    store=Store();invoke=Mock(return_value=response());prepare(store,invoke)
    plan=store.value['state']['experimentPlanning']
    if corruption=='basis':plan['basis']['protocol']['data']='changed independently'
    elif corruption=='response':plan['response']['content']='invalid'
    elif corruption=='request':plan['request']['prompt']='changed'
    else:plan[corruption]='changed'
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1


@pytest.mark.parametrize('bad',[{},[],{'sourceFacts':[],'protocol':{},'unresolved':[]},
    {'sourceFacts':[{'topic':'invented source','scope':'wrong','evidenceRefs':['E99']}],
     'protocol':basis()['protocol'],'unresolved':[]},
    {'sourceFacts':basis()['sourceFacts'],'protocol':basis()['protocol'],'unresolved':['x'*MAX_BASIS_BYTES]}])
def test_received_invalid_plan_is_saved_and_never_automatically_retried(bad):
    store=Store();invoke=Mock(return_value=response(bad))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert store.value['state']['experimentPlanning']['status']=='invalid_response'
    assert store.value['state']['experimentPlanning']['response']==response(bad)
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1


@pytest.mark.parametrize('bad_response',[{'content':'{incomplete'},
    {**response(),'finishReason':'length'},{'content':response()['content'],'finish_reason':'length'},None])
def test_truncation_and_nonobjects_do_not_fall_back_to_direct_generation(bad_response):
    store=Store();invoke=Mock(return_value=bad_response)
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert store.value['state']['experimentPlanning']['status']=='invalid_response'
    assert invoke.call_count==1


def test_successful_response_checkpoint_restores_even_before_parse_finishes():
    store=Store();invoke=Mock(return_value=response());prepare(store,invoke)
    plan=store.value['state']['experimentPlanning'];plan['status']='response_received';plan.pop('basis')
    assert prepare(store,invoke)['basis']==basis() and invoke.call_count==1
    plan=store.value['state']['experimentPlanning'];plan['status']='response_received'
    plan['response']['content']='changed'
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1


def test_unknown_keeps_exact_pending_request_for_normal_ledger_guard():
    store=Store()
    invoke=Mock(side_effect=DeepResearchError('unknown','unknown outcome; do not send'))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    pending=deepcopy(store.value['state']['experimentPlanning'])
    assert pending['status']=='pending' and 'response' not in pending
    store.value['budget']['elapsedSeconds']=360
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_args_list[0]==invoke.call_args_list[1]
    assert store.value['state']['experimentPlanning']==pending


def test_new_planning_and_new_body_refuse_insufficient_time_before_invoke():
    store=Store();store.value['budget']['elapsedSeconds']=211;invoke=Mock()
    assert prepare(store,invoke) is None
    assert store.value['state']['experimentPlanning']['status']=='not_started_budget'
    store.value['budget']['elapsedSeconds']=0
    assert prepare(store,invoke) is None;invoke.assert_not_called()
    store=Store();plan=prepare(store,Mock(return_value=response()))
    store.value['budget']['elapsedSeconds']=271
    assert prepare_draft(store.value,plan,prompt='body',checkpoint=store.checkpoint) is None
    assert 'draftRequest' not in store.value['state']['experimentPlanning']


def test_elapsed_admission_includes_clock_time_and_does_not_depend_only_on_stale_counter():
    value=current();value['startedAt']=(datetime.now(UTC)-timedelta(seconds=230)).isoformat()
    assert 129<remaining_seconds(value)<131


@pytest.mark.parametrize('version',[None,True,'3',0,1,2,4])
def test_old_versions_keep_existing_request_path(version):
    value=current();value['experimentDraftContractVersion']=version
    assert not enabled(value)


def test_capacity_and_citation_permissions_fail_before_sending_and_do_not_mutate_sources():
    store=Store();invoke=Mock();before=deepcopy(store.value)
    with pytest.raises(DeepResearchError):prepare(store,invoke,prompt='文'*8001)
    invoke.assert_not_called();assert store.value==before
    assert validate_basis(basis(),{'E1':'eq'})
    invalid=basis();invalid['sourceFacts'][0]['evidenceRefs']=['E1','E1']
    assert not validate_basis(invalid,{'E1':'eq'})
    invalid=basis();invalid['protocol']['data']=True
    assert not validate_basis(invalid,{'E1':'eq'})


def test_body_unknown_resume_does_not_regenerate_plan_or_change_actual_request():
    store=Store();requests=[]
    def invoke(_id,node,prompt,extra,**_kw):
        requests.append((node,prompt,extra))
        if node=='plan_experiment':return response()
        raise DeepResearchError('unknown','saved body unknown; no physical resend')
    with pytest.raises(DeepResearchError):make_synthesize_node(invoke,store.update)({'run_id':'r'})
    store.value['budget']['elapsedSeconds']=999
    with pytest.raises(DeepResearchError):make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert [request[0] for request in requests]==['plan_experiment','synthesize','synthesize']
    assert requests[1]==requests[2]


def test_native_ledger_fingerprint_reservation_and_unknown_guard_match_frozen_plan():
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.contracts import UnknownCallError
    from services.deep_research.tools import TrackedLLMInvoker
    store=Store();provider=Mock()
    provider.invoke.return_value=LLMResult(content=response()['content'],provider='fixture',model='fixture',
        usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False))
    tracked=TrackedLLMInvoker(provider,reserve,Mock(),request_options=research_model_options,
        run_record_fn=lambda _:store.value)
    invoke=lambda node,prompt,extra:tracked('r',node,prompt,extra,use_reserve=True)
    ready=prepare(store,invoke)
    assert reserve.call_args.kwargs['args_digest']==digest(ready['request'])
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(ready['request']['prompt'].encode())+1024+6144
    assert provider.invoke.call_args.args[0].extra_body==ready['request']['extra']
    # Simulate a crash after a settled provider call but before saving its response.
    store.value['state']['experimentPlanning']=deepcopy(store.checkpoints[0])
    reserve.return_value=({'callId':'c','result':response()},True)
    assert prepare(store,invoke)['basis']==basis() and provider.invoke.call_count==1
    store.value['state']['experimentPlanning']=deepcopy(store.checkpoints[0])
    reserve.side_effect=UnknownCallError('c')
    with pytest.raises(UnknownCallError):prepare(store,invoke)
    assert provider.invoke.call_count==1


def test_both_stages_use_one_authoritative_budget_and_cannot_exceed_its_call_cap(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.contracts import BudgetExhaustedError
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.provider import LLMResult,LLMUsage
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    value=current();value.update(taskId='t',budget={
        'maxModelCalls':2,'reserveModelCalls':1,'maxTokens':100000,'reserveTokens':30000,
        'maxWallClockSeconds':360,'finalizationBudgetVersion':1})
    value,_=repo.create_run(value);run_id=value['runId'];repo.begin_execution(run_id)
    provider=Mock();provider.invoke.return_value=LLMResult(content=response()['content'],
        provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    tracked=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call,
        request_options=research_model_options,run_record_fn=repo.require_run)
    plan_request=request_identity(value,'plan_experiment','source',{'max_tokens':6144,'temperature':0.0})
    tracked(run_id,'plan_experiment','source',plan_request['extra'],use_reserve=True)
    tracked(run_id,'synthesize','same source and plan',{},use_reserve=True)
    with pytest.raises(BudgetExhaustedError):
        tracked(run_id,'verify','third request cannot increase the cap',{},use_reserve=True)
    assert provider.invoke.call_count==2
    budget=repo.require_run(run_id)['budget']
    assert budget['modelCalls']+budget['reservedModelCalls']==2
    assert budget['maxModelCalls']==2 and budget['maxTokens']==100000 and budget['maxWallClockSeconds']==360
