import asyncio
import json
import sqlite3
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError,RunNotFoundError,digest
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.research_engine_dispatch import ResearchEngineDispatcher,configure_dispatcher


def stored(tmp_path,status='pending'):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'parent','taskId':'task','workspaceId':'task'})
    fingerprint=digest({'action':'continue','runId':'parent','payload':{'requestId':'req'}})
    repo.claim_action('parent','req',fingerprint)
    if status!='pending':repo.finish_action('parent','req',{'error':{'code':'idempotency_conflict'}} if status=='failed' else {'runId':'child'},status=status)
    return repo,fingerprint


def snapshot(repo):
    with sqlite3.connect(repo.db_path) as con:
        return {table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            for table in ('deep_research_runs_v2','deep_research_actions_v2','deep_research_calls_v2','deep_research_outbox_v2')}


@pytest.mark.parametrize('status',['pending','completed','failed'])
def test_action_lookup_preserves_exact_status_payload_fingerprint_and_all_tables(tmp_path,status):
    repo,fingerprint=stored(tmp_path,status);before=snapshot(repo)
    facade=ResearchFacade(repo,lambda **_:pytest.fail('GET cannot run graph'),llm_client=object())
    try:
        result=facade.get_action_receipt('parent','req')
        assert result['runId']=='parent' and result['taskId']=='task' and result['requestId']=='req'
        assert result['fingerprint']==fingerprint and result['status']==status and result['matchingChildRuns']==[]
        result['status']='tampered'
        assert facade.get_action_receipt('parent','req')['status']==status and snapshot(repo)==before
    finally:facade.shutdown()


def test_only_same_operation_key_and_exact_parent_child_is_exposed(tmp_path):
    repo,_=stored(tmp_path,'completed')
    for rid,task,parent,key in [('child','task','parent','req'),('other-parent','other','other-parent','req'),
        ('other-operation','task','parent','different')]:
        repo.create_run({'runId':rid,'taskId':task,'workspaceId':task,'parentRunId':parent,'idempotencyKey':key})
    before=snapshot(repo);value=repo.get_action_receipt('parent','req')
    assert [r['runId'] for r in value['matchingChildRuns']]==['child']
    assert set(value['matchingChildRuns'][0])=={'runId','taskId','parentRunId','status','errorCode'}
    assert snapshot(repo)==before


def test_missing_receipt_does_not_claim_one_and_missing_run_is_not_fabricated(tmp_path):
    repo,_=stored(tmp_path);before=snapshot(repo)
    assert repo.get_action_receipt('parent','missing') is None
    with pytest.raises(RunNotFoundError):repo.get_action_receipt('missing','req')
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        with pytest.raises(DeepResearchError) as exc:facade.get_action_receipt('parent','missing')
        assert exc.value.code=='action_not_found' and exc.value.details['status_code']==404
        assert snapshot(repo)==before
    finally:facade.shutdown()


@pytest.mark.parametrize('request_id',[None,True,'',' ','x'*257])
def test_invalid_request_ids_never_read_or_mutate_actions(tmp_path,request_id):
    repo,_=stored(tmp_path);before=snapshot(repo)
    with pytest.raises(ValueError):repo.get_action_receipt('parent',request_id)
    assert snapshot(repo)==before


def test_real_dispatch_and_route_read_only_do_not_call_actions_or_legacy(tmp_path):
    from routes import research_routes
    repo,fingerprint=stored(tmp_path,'failed');before=snapshot(repo)
    facade=ResearchFacade(repo,lambda **_:pytest.fail('No graph'),llm_client=object());legacy=Mock()
    service=ResearchEngineDispatcher(facade=facade,lookup=repo.get_run,legacy=legacy)
    configure_dispatcher(service)
    try:
        response=asyncio.run(research_routes.get_research_action_receipt('parent','req'))
        assert response.status_code==200 and json.loads(response.body)['receipt']['fingerprint']==fingerprint
        assert json.loads(response.body)['receipt']['status']=='failed'
        response=asyncio.run(research_routes.get_research_action_receipt('parent','absent'))
        assert response.status_code==404 and json.loads(response.body)['errorCode']=='action_not_found'
        with pytest.raises(DeepResearchError):service.get_action_receipt('legacy','req')
        legacy.assert_not_called();assert not legacy.mock_calls and snapshot(repo)==before
    finally:configure_dispatcher(None);facade.shutdown()
