from copy import deepcopy
from datetime import datetime,UTC,timedelta
from types import SimpleNamespace

import pytest

from services.deep_research.elapsed_accounting import enabled,freeze_transition,public_elapsed
from services.deep_research.facade import ResearchFacade,_elapsed_seconds
from services.deep_research.repository import DeepResearchRepository


def iso(value):return value.isoformat().replace('+00:00','Z')


def setup(tmp_path,monkeypatch,graph=None,model=None):
    import services.deep_research.repository as repository
    import services.deep_research.facade as facade_module
    clock={'at':datetime.now(UTC).replace(microsecond=0)}
    monkeypatch.setattr(repository,'utc_now_iso',lambda:iso(clock['at']))
    monkeypatch.setattr(facade_module,'utc_now_iso',lambda:iso(clock['at']))
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,graph or (lambda **_:None),llm_client=model or object())
    r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较原文事实','deferStart':True},start_async=False)
    repo.begin_execution(r['runId'])
    return repo,facade,r['runId'],clock


@pytest.mark.parametrize('status',['paused','waiting_user','failed','completed','cancelled'])
def test_stopping_clock_is_persisted_and_metadata_edits_cannot_age_it(tmp_path,monkeypatch,status):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        clock['at']+=timedelta(seconds=49)
        saved=repo.transition(rid,status)
        assert saved['budget']['elapsedSeconds']==49 and _elapsed_seconds(saved)==49
        assert saved['budget']['elapsedMeasurement']=='wall_clock'
        before=deepcopy(saved['budget']);clock['at']+=timedelta(hours=2)
        changed=repo.update_run(rid,lambda r:{**r,'title':'metadata only'})
        assert changed['budget']==before and facade.get(rid)['budget']['elapsedSeconds']==49
        reopened=DeepResearchRepository(repo.db_path)
        assert reopened.require_run(rid)==changed
    finally:facade.shutdown()


@pytest.mark.parametrize('from_status',['running','stopping'])
def test_recovery_freezes_a_conservative_wall_bound_once_and_keeps_pending_unknown(tmp_path,monkeypatch,from_status):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        pending=repo.reserve_call(run_id=rid,node='read',tool='llm_invoke',args_digest='original',budget_delta={'modelCalls':1,'tokens':100})
        if from_status=='stopping':repo.transition(rid,'stopping')
        clock['at']+=timedelta(seconds=49);repo.recover()
        saved=repo.require_run(rid);calls=repo.list_calls(rid)
        assert saved['status']==('paused' if from_status=='running' else 'cancelled')
        assert saved['budget']['elapsedSeconds']==49
        assert saved['budget']['elapsedMeasurement']=='recovery_wall_clock_upper_bound'
        assert len(calls)==1 and calls[0]['status']=='unknown' and not calls[0]['settled']
        assert saved['budget']['tokens']==100
        clock['at']+=timedelta(hours=2);repo.recover()
        assert repo.require_run(rid)==saved and repo.list_calls(rid)==calls
    finally:facade.shutdown()


def test_waiting_to_pause_keeps_the_existing_frozen_clock_and_resume_does_not_extend_deadline(tmp_path,monkeypatch):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        original_start=repo.require_run(rid)['startedAt'];clock['at']+=timedelta(seconds=49)
        repo.transition(rid,'paused');clock['at']+=timedelta(seconds=20)
        resumed=repo.begin_execution(rid)
        assert resumed['startedAt']==original_start
        assert public_elapsed(resumed,now=clock['at'])==69
        assert resumed['budget']['maxWallClockSeconds']==360
        clock['at']+=timedelta(seconds=1)
        waiting=repo.transition(rid,'waiting_user')
        assert waiting['budget']['elapsedSeconds']==70
        clock['at']+=timedelta(hours=1)
        paused=repo.transition(rid,'paused')
        assert paused['budget']['elapsedSeconds']==70 and _elapsed_seconds(paused)==70
    finally:facade.shutdown()


def test_publication_clock_matches_finished_at_and_does_not_age_on_outbox_changes(tmp_path,monkeypatch):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        clock['at']+=timedelta(seconds=49)
        repo.publish_report(run_id=rid,dedup_key='pub',payload={'reportVersionId':'report','body':'fixture'},outcome='partial')
        saved=repo.require_run(rid)
        assert saved['budget']['elapsedSeconds']==49 and saved['finishedAt']==iso(clock['at'])
        clock['at']+=timedelta(hours=1)
        assert _elapsed_seconds(repo.require_run(rid))==49
    finally:facade.shutdown()


def test_clarification_wait_is_excluded_once_by_the_existing_resume_clock(tmp_path,monkeypatch):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        clock['at']+=timedelta(seconds=49)
        repo.transition(rid,'waiting_user',mutate=lambda r:{**r,'state':{**r['state'],'waitingSince':iso(clock['at'])}})
        clock['at']+=timedelta(hours=1)
        assert facade.get(rid)['budget']['elapsedSeconds']==49
        resumed=repo.begin_execution(rid)
        assert resumed['budget']['waitingSeconds']==3600 and resumed['state']['waitingSince'] is None
        clock['at']+=timedelta(seconds=5)
        assert public_elapsed(repo.require_run(rid),now=clock['at'])==54
        assert repo.require_run(rid)['budget']['maxWallClockSeconds']==360
    finally:facade.shutdown()


def test_late_audit_response_preserves_frozen_time_and_all_authoritative_run_counters(tmp_path,monkeypatch):
    repo,facade,rid,clock=setup(tmp_path,monkeypatch)
    try:
        pending,_=repo.reserve_call(run_id=rid,node='read',tool='llm_invoke',args_digest='original',budget_delta={'modelCalls':1,'tokens':100})
        clock['at']+=timedelta(seconds=49);repo.transition(rid,'paused')
        before=repo.require_run(rid);clock['at']+=timedelta(minutes=2)
        repo.complete_call(pending['callId'],status='succeeded',result={'fixture':'known response'},budget_delta={'tokens':30},allow_late=True)
        assert repo.require_run(rid)==before and facade.get(rid)['budget']['elapsedSeconds']==49
        assert repo.list_calls(rid)[0]['status']=='succeeded'
    finally:facade.shutdown()


@pytest.mark.parametrize('http,status',[(500,'paused'),(402,'failed')])
def test_actual_worker_failure_persists_time_and_does_not_reissue_unknowns(tmp_path,monkeypatch,http,status):
    from llm.provider import LLMProviderError
    from services.deep_research.contracts import UnresolvedUnknownError
    holder={};requests=[]
    class Model:
        def invoke(self,request):
            requests.append(request);holder['clock']['at']+=timedelta(seconds=49)
            raise LLMProviderError('private diagnostic',provider='fixture',model='fixture',status_code=http,retryable=http==500)
    def graph(**deps):
        def invoke(state,config):
            return deps['llm_invoke'](state['run_id'],'assess_relevance','fixture',{'max_tokens':16})
        return SimpleNamespace(checkpointer=None,invoke=invoke)
    repo,facade,rid,clock=setup(tmp_path,monkeypatch,graph,Model());holder['clock']=clock
    try:
        facade._execute_graph(rid);saved=repo.require_run(rid);calls=repo.list_calls(rid)
        assert saved['status']==status and saved['budget']['elapsedSeconds']==49
        assert facade.get(rid)['budget']['elapsedSeconds']==49 and len(requests)==1
        assert len(calls)==1 and calls[0]['status']==('unknown' if http==500 else 'failed')
        assert not repo.list_outbox(rid)
        if http==500:
            assert calls[0]['reservedTokens']>0 and not calls[0]['settled']
            with pytest.raises(UnresolvedUnknownError):repo.begin_execution(rid)
            assert repo.require_run(rid)==saved and repo.list_calls(rid)==calls
    finally:facade.shutdown()


@pytest.mark.parametrize('value',[None,True,0,2,'1'])
def test_policy_is_strict_and_legacy_records_are_not_migrated(value):
    old={'elapsedAccountingContractVersion':value,'status':'running','startedAt':'2026-01-01T00:00:00Z','budget':{'elapsedSeconds':0}}
    update={**old,'status':'paused'};before=deepcopy(update)
    assert not enabled(old) and freeze_transition(old,update,'2026-01-01T00:00:49Z')==before


@pytest.mark.parametrize('value',[None,True,0,2])
def test_server_policy_is_immutable_and_client_value_is_ignored(tmp_path,value):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'研究','deferStart':True,'elapsedAccountingContractVersion':value},start_async=False)
        assert r['elapsedAccountingContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'elapsedAccountingContractVersion':value})
    finally:facade.shutdown()
