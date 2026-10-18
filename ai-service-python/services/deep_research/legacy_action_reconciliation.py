"""Exact GET-only reconciliation of a legacy, unconfirmed continuation intent.

Only a definitive idempotency conflict before child creation is recognized.
This never settles a provider unknown, changes the original receipt, confirms a
child, or retries an action. Every later admission rechecks the live receipt.
"""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from services.deep_research.contracts import digest

_FIELDS={'requestId','expectedRunRevision','question','budgetProfile','sourcePolicy'}


def _identity(path,case_id):
    path=Path(path);raw=path.read_bytes()
    if len(raw)>64000:raise ValueError('Legacy intent is too large to reconcile')
    saved=json.loads(raw)
    if (not isinstance(saved,dict) or 'schemaVersion' in saved or 'intent' in saved
            or saved.get('case')!=case_id or 'runId' not in saved or saved.get('runId') is not None
            or not isinstance(saved.get('input'),dict)):
        raise ValueError('Only an exact unconfirmed legacy continuation intent can be reconciled')
    body=saved['input']
    if set(body)-_FIELDS:raise ValueError('Legacy continuation has unsupported forwarding fields')
    for value in (saved.get('taskId'),saved.get('parentRunId'),body.get('requestId')):
        if not isinstance(value,str) or not value.strip() or len(value)>256:
            raise ValueError('Legacy continuation identity is invalid')
    if type(body.get('expectedRunRevision')) is not int or body['expectedRunRevision']<0:
        raise ValueError('Exact original expected revision is required')
    if not isinstance(body.get('question'),str) or not body['question'].strip():
        raise ValueError('Exact original follow-up question is required')
    forwarded={**body,'parentRunId':saved['parentRunId'],'deferStart':True}
    return {'schemaVersion':1,'kind':'definitive_pre_child_failure','caseId':case_id,
        'receiptSha256':hashlib.sha256(raw).hexdigest(),'taskId':saved['taskId'],
        'parentRunId':saved['parentRunId'],'requestId':body['requestId'],
        'fingerprint':digest({'action':'continue','payload':forwarded,'runId':saved['parentRunId']}),
        'receiptStatus':'failed','failureCode':'idempotency_conflict'}


def _require_live_failure(identity,api):
    path='/task-workspaces/'+quote(identity['taskId'],safe='')+'/research/'+quote(identity['parentRunId'],safe='')
    response=api('GET',path+'/actions/'+quote(identity['requestId'],safe=''))
    receipt=response.get('receipt') if isinstance(response,dict) and response.get('status')=='success' else None
    if not isinstance(receipt,dict):raise ValueError('Authoritative action receipt is missing')
    for key,expected in [('runId',identity['parentRunId']),('taskId',identity['taskId']),
                         ('requestId',identity['requestId']),('fingerprint',identity['fingerprint']),('status','failed')]:
        if receipt.get(key)!=expected:raise ValueError('Authoritative action identity or terminal status mismatch')
    result=receipt.get('result');error=result.get('error') if isinstance(result,dict) else None
    details=error.get('details') if isinstance(error,dict) else None
    if (not isinstance(error,dict) or error.get('code')!='idempotency_conflict'
            or not isinstance(details,dict) or details.get('workspaceId')!=identity['taskId']
            or details.get('idempotencyKey')!=identity['requestId']
            or receipt.get('matchingChildRuns')!=[]):
        raise ValueError('No definitive pre-child idempotency failure; keep original submission blocked')
    return receipt


def resolution_path(path):
    return Path(path).with_suffix('.resolution.json')


def reconcile_legacy_failure(path,case_id,api):
    """Write a separate immutable identity seal after a live GET, never POST."""
    identity=_identity(path,case_id);sidecar=resolution_path(path)
    if sidecar.exists():
        require_live_legacy_resolution(path,case_id,api)
        return identity
    _require_live_failure(identity,api)
    with sidecar.open('x',encoding='utf8') as stream:
        json.dump(identity,stream,ensure_ascii=False,allow_nan=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    return identity


def require_live_legacy_resolution(path,case_id,api):
    identity=_identity(path,case_id)
    saved=json.loads(resolution_path(path).read_text(encoding='utf8'))
    if saved!=identity:raise ValueError('Legacy action resolution differs from the original frozen intent')
    _require_live_failure(identity,api)
    return identity
