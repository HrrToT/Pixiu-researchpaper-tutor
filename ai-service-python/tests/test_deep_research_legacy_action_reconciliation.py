from copy import deepcopy
import json

import pytest

from services.deep_research.legacy_action_reconciliation import (
    _identity,reconcile_legacy_failure,require_live_legacy_resolution,resolution_path)
from scripts.verify_deep_research_case import require_previous_cases_settled,run_case
from test_deep_research_acceptance_receipts import manifest


def legacy(tmp_path):
    path=tmp_path/'D-v1.json';path.write_text(json.dumps({'case':'D','taskId':'task','parentRunId':'parent',
        'runId':None,'input':{'requestId':'request','expectedRunRevision':127,'question':'Continue the comparison',
        'budgetProfile':'standard'}}),encoding='utf8')
    return path


def response(path):
    identity=_identity(path,'D')
    return {'status':'success','receipt':{'runId':'parent','taskId':'task','requestId':'request',
        'fingerprint':identity['fingerprint'],'status':'failed',
        'result':{'error':{'code':'idempotency_conflict','details':{'workspaceId':'task','idempotencyKey':'request'}}},
        'matchingChildRuns':[]}}


def test_get_only_seal_preserves_original_bytes_and_rechecks_live_on_every_admission(tmp_path):
    path=legacy(tmp_path);original=path.read_bytes();calls=[]
    def api(method,target):
        calls.append((method,target));return response(path)
    first=reconcile_legacy_failure(path,'D',api)
    assert path.read_bytes()==original and resolution_path(path).exists()
    assert reconcile_legacy_failure(path,'D',api)==first
    require_previous_cases_settled(tmp_path,'D',api)
    assert len(calls)==3 and all(method=='GET' and target.endswith('/parent/actions/request') for method,target in calls)


@pytest.mark.parametrize('field,value',[('runId','other'),('taskId','foreign'),('requestId','other'),
    ('fingerprint','b'*64),('status','pending'),('status','completed'),('matchingChildRuns',None),
    ('matchingChildRuns',[{'runId':'child'}]),('result',{'error':{'code':'unresolved_unknown'}})])
def test_missing_changed_pending_child_or_provider_unknown_never_get_a_resolution(tmp_path,field,value):
    path=legacy(tmp_path);original=path.read_bytes();actual=response(path);actual['receipt'][field]=value
    with pytest.raises(ValueError):reconcile_legacy_failure(path,'D',lambda *_:actual)
    assert not resolution_path(path).exists() and path.read_bytes()==original


@pytest.mark.parametrize('field,value',[('workspaceId','foreign'),('idempotencyKey','other')])
def test_error_scope_is_part_of_the_exact_failed_action_identity(tmp_path,field,value):
    path=legacy(tmp_path);actual=response(path);actual['receipt']['result']['error']['details'][field]=value
    with pytest.raises(ValueError):reconcile_legacy_failure(path,'D',lambda *_:actual)
    assert not resolution_path(path).exists()


def test_cached_resolution_cannot_hide_new_child_or_repair_a_changed_original(tmp_path):
    path=legacy(tmp_path);actual=response(path);reconcile_legacy_failure(path,'D',lambda *_:actual)
    actual['receipt']['matchingChildRuns']=[{'runId':'child'}]
    with pytest.raises(ValueError):require_previous_cases_settled(tmp_path,'D',lambda *_:actual)
    original=json.loads(path.read_text(encoding='utf8'));original['input']['question']='Changed follow-up'
    path.write_text(json.dumps(original),encoding='utf8');calls=[]
    with pytest.raises(ValueError):require_live_legacy_resolution(path,'D',lambda *a:calls.append(a))
    assert calls==[]


def test_incomplete_new_style_or_fresh_scope_intent_cannot_borrow_legacy_resolution(tmp_path):
    path=legacy(tmp_path);saved=json.loads(path.read_text(encoding='utf8'))
    for key,value in [('materialSelection',{'mode':'external_only'}),('freshContinuation',True)]:
        altered=deepcopy(saved);altered['input'][key]=value;path.write_text(json.dumps(altered),encoding='utf8')
        with pytest.raises(ValueError):reconcile_legacy_failure(path,'D',lambda *_:pytest.fail('No HTTP'))
    path.write_text(json.dumps({'schemaVersion':1,'intent':{},'runId':None}),encoding='utf8')
    with pytest.raises(ValueError):reconcile_legacy_failure(path,'D',lambda *_:pytest.fail('No HTTP'))


def test_reconciled_failed_intent_does_not_bypass_another_unknown_run(tmp_path):
    path=legacy(tmp_path);reconcile_legacy_failure(path,'D',lambda *_:response(path))
    (tmp_path/'D-v2.json').write_text(json.dumps({'case':'D','taskId':'task','runId':'unknown'}),encoding='utf8')
    def api(method,target):
        if '/actions/' in target:return response(path)
        return {'task':{'taskId':'task','runId':'unknown','status':'paused','errorCode':'unresolved_unknown'}}
    with pytest.raises(ValueError,match='confirmed terminal outcome'):require_previous_cases_settled(tmp_path,'D',api)


def test_explicit_new_attempt_requires_fresh_resolution_and_all_prior_terminals(tmp_path):
    path=legacy(tmp_path);reconcile_legacy_failure(path,'D',lambda *_:response(path));calls=[]
    (tmp_path/'D-v2.json').write_text(json.dumps({'case':'D','taskId':'old','runId':'completed'}),encoding='utf8')
    def api(method,target,**kwargs):
        calls.append((method,target))
        if '/actions/' in target:return response(path)
        if target.endswith('/completed'):return {'task':{'taskId':'old','runId':'completed','status':'completed'}}
        if target.endswith('/start') or target.endswith('/new'):return {'task':{'taskId':'task','runId':'new','status':'running'}}
        return {'revision':1,'paperIds':['hash.pdf']}
    value=run_case(manifest(),'D',3,tmp_path,api,submit=True,task_id='task')
    assert value['runId']=='new'
    assert calls[:2]==[('GET','/task-workspaces/task/research/parent/actions/request'),
        ('GET','/task-workspaces/old/research/completed')]
    assert [r for r in calls if r[0]=='POST']==[('POST','/task-workspaces/task/research/start')]
