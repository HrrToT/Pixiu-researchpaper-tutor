"""Exercise the production factory's rollout gate without a live provider."""
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.repository import digest
from test_deep_research_runtime_isolation import production_factory


def parent(facade):
    record, _ = facade.create({'workspaceTaskId':'rollback-task','operationKey':'parent',
        'question':'解释研究边界','deferStart':True}, start_async=False)
    facade._repo.begin_execution(record['runId'])
    return facade._repo.update_run(record['runId'], lambda r: {**r,'status':'completed'})


def test_rollback_rejects_new_continuation_before_claiming_receipt(production_factory, monkeypatch):
    facade, captured = production_factory
    record=parent(facade); rid=record['runId']
    payload={'requestId':'new-child','expectedRunRevision':record['runRevision'],'deferStart':True}
    before=facade._repo.list_runs()
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    with pytest.raises(DeepResearchError) as error:facade.action(rid,'continue',payload)
    assert error.value.code=='engine_unavailable' and error.value.details['status_code']==503
    assert facade._repo.get_action_receipt(rid,'new-child') is None
    assert facade._repo.list_runs()==before and captured==[]
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','true')
    child=facade.action(rid,'continue',payload)
    assert child['parentRunId']==rid and len(facade._repo.list_runs())==2 and captured==[]


def test_rollback_factory_cannot_create_directly(production_factory, monkeypatch):
    facade,captured=production_factory
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    with pytest.raises(DeepResearchError) as error:
        facade.create({'workspaceTaskId':'rollback-task','operationKey':'new','question':'新研究'},start_async=False)
    assert error.value.code=='engine_unavailable'
    assert facade._repo.list_runs()==[] and captured==[]


def test_rollback_state_does_not_offer_an_unavailable_new_child(production_factory, monkeypatch):
    facade,captured=production_factory;record=parent(facade);rid=record['runId']
    assert 'continue' in facade.get(rid)['allowedActions']
    before=facade._repo.require_run(rid)
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    assert 'continue' not in facade.get(rid)['allowedActions']
    assert facade._repo.require_run(rid)==before and captured==[]
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','true')
    assert 'continue' in facade.get(rid)['allowedActions']


def test_rollback_keeps_completed_continuation_receipt_idempotent(production_factory, monkeypatch):
    facade,captured=production_factory
    record=parent(facade);rid=record['runId']
    payload={'requestId':'completed-child','expectedRunRevision':record['runRevision'],'deferStart':True}
    result=facade.action(rid,'continue',payload)
    before=facade._repo.list_runs()
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    assert facade.action(rid,'continue',payload)==result
    assert facade._repo.list_runs()==before and len(before)==2 and captured==[]
    with pytest.raises(DeepResearchError) as error:facade.action(rid,'continue',{**payload,'question':'不同负载'})
    assert error.value.code=='idempotency_conflict'


@pytest.mark.parametrize('receipt_status,code',[('pending','unknown_action'),('failed','fixture_failure')])
def test_rollback_does_not_reissue_saved_pending_or_failed_actions(production_factory,monkeypatch,receipt_status,code):
    facade,captured=production_factory;record=parent(facade);rid=record['runId']
    payload={'requestId':'saved','expectedRunRevision':record['runRevision'],'deferStart':True}
    fingerprint=digest({'action':'continue','payload':payload,'runId':rid})
    facade._repo.claim_action(rid,'saved',fingerprint)
    if receipt_status=='failed':facade._repo.finish_action(rid,'saved',{'error':{'code':code,'message':'saved failure'}},status='failed')
    before=facade._repo.list_runs();receipt=facade._repo.get_action_receipt(rid,'saved')
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    with pytest.raises(DeepResearchError) as error:facade.action(rid,'continue',payload)
    assert error.value.code==code
    assert facade._repo.get_action_receipt(rid,'saved')==receipt
    assert facade._repo.list_runs()==before and captured==[]


def test_rollback_retains_read_and_cancel_for_existing_engine(production_factory,monkeypatch):
    facade,captured=production_factory
    record,_=facade.create({'workspaceTaskId':'rollback-task','operationKey':'queued','question':'已有研究','deferStart':True},start_async=False)
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    assert facade.get(record['runId'])['runId']==record['runId']
    result=facade.action(record['runId'],'cancel',{'requestId':'cancel','expectedRunRevision':record['runRevision']})
    assert result['status']=='cancelled' and len(facade._repo.list_runs())==1 and captured==[]


def test_restart_with_rollout_off_retains_existing_run_and_store(production_factory,monkeypatch):
    from services.deep_research import runtime
    facade,captured=production_factory
    record=parent(facade);rid=record['runId']
    # Stored publication fixture proves report readability, without claiming
    # that fixture content was scientifically verified or generated live.
    facade._repo.update_run(rid,lambda r:{**r,'report':'合成历史报告正文',
        'publication':{'publicationId':'rollback-publication'},
        'state':{**r.get('state',{}),'publicationId':'rollback-publication',
                 'reportVersionId':'rollback-version','reportText':'合成历史报告正文'}})
    before=facade._repo.require_run(rid)
    runtime.shutdown_runtime()
    monkeypatch.setenv('DEEP_RESEARCH_V2_ENABLED','false')
    restored=runtime.initialize_runtime()
    try:
        assert restored is not None
        assert restored._repo.require_run(rid)==before
        assert restored.get(rid)['runId']==rid
        assert restored.get(rid)['engineVersion']=='deep-research-v2'
        assert restored.get(rid)['report']['body']=='合成历史报告正文'
        assert restored.get(rid)['report']['versionId']=='rollback-version'
        with pytest.raises(DeepResearchError) as error:
            restored.action(rid,'continue',{'requestId':'after-restart','expectedRunRevision':before['runRevision'],'deferStart':True})
        assert error.value.code=='engine_unavailable'
        assert len(restored._repo.list_runs())==1 and captured==[]
    finally:
        runtime.shutdown_runtime()
