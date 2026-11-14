"""Opt-in loopback Java/Python publication drill with synthetic content only.

Requires a built project JAR, Java and the project's Python environment. No
model/graph worker is executed. Never point this at an existing database.
"""
from pathlib import Path
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--java', required=True, type=Path)
parser.add_argument('--jar', required=True, type=Path)
parser.add_argument('--run-id', required=True)
args = parser.parse_args()
assert re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id), 'Invalid run ID'
root = Path(__file__).resolve().parents[1]
java, jar = args.java.resolve(strict=True), args.jar.resolve(strict=True)
work = root / 'tmp' / ('publication-integration-' + args.run_id)
for port in (8189, 8193):
    with socket.socket() as conn:
        assert conn.connect_ex(('127.0.0.1', port)) != 0, 'An isolated port is occupied'
work.mkdir(exist_ok=False)
sys.path.insert(0, str(root / 'ai-service-python'))
os.environ.update(DEEP_RESEARCH_V2_ENABLED='true', DEEP_RESEARCH_EXTERNAL_ENABLED='true',
    DEEP_RESEARCH_FULLTEXT_ENABLED='false', DEEP_RESEARCH_DB_PATH=str(work / 'research.sqlite3'),
    DEEP_RESEARCH_JAVA_ORIGIN='http://127.0.0.1:8189/api')

import requests
import uvicorn
from fastapi import FastAPI
from services.deep_research import runtime
from services.deep_research.publication import PublicationDispatcher
from routes.research_routes import research_router

http_log, scheduled, blocked = [], [], []
original_send, original_init = requests.Session.send, requests.Session.__init__
def local_session(self, *a, **kw):
    original_init(self, *a, **kw)
    self.trust_env = False
def loopback_send(self, request, **kwargs):
    target = urlparse(request.url)
    if target.hostname != '127.0.0.1' or target.port not in (8189, 8193):
        blocked.append(request.method + ' ' + request.url)
        raise AssertionError('Non-isolated HTTP request blocked')
    response = original_send(self, request, **kwargs)
    http_log.append({'method': request.method, 'path': target.path, 'port': target.port, 'status': response.status_code})
    return response
requests.Session.__init__, requests.Session.send = local_session, loopback_send
class ForbiddenModel:
    def invoke(self, *a, **kw):
        blocked.append('model invocation')
        raise AssertionError('No model invocation permitted')
runtime.research_model = lambda: ForbiddenModel()
# Delivery is driven explicitly to make a lost acknowledgment reproducible.
PublicationDispatcher.start = lambda self: None
app = FastAPI()
app.include_router(research_router, prefix='/api')
@app.get('/probe')
def probe():
    return {'isolated': True}
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8193, log_level='error', access_log=False))
thread = threading.Thread(target=server.run, daemon=True)
session = requests.Session()
base = 'http://127.0.0.1:8189/api'
process = log = facade = None
proof = {'modelCalls': 0, 'productionWrites': 0, 'jarSha256': hashlib.sha256(jar.read_bytes()).hexdigest(),
    'workerBoundary': 'Actual HTTP routes/repository/publication dispatcher; graph worker replaced by a completed no-op Future',
    'contentBoundary': 'Synthetic stored report, not a generated or scientifically accepted research answer'}

def request(method, path, data=None, status=200):
    response = session.request(method, base + path, json=data, timeout=15)
    assert response.status_code == status, f'{method} {path}: expected {status}, got {response.status_code}: {response.text[:400]}'
    return response.json() if response.content else None

def start_java(index):
    out = (work / f'java-{index}.log').open('x', encoding='utf8')
    proc = subprocess.Popen([str(java), '-jar', str(jar), '--server.address=127.0.0.1', '--server.port=8189',
        '--spring.datasource.url=jdbc:h2:file:./db/integration;DB_CLOSE_ON_EXIT=FALSE',
        '--PYTHON_URL=http://127.0.0.1:8193/api'], cwd=work, stdout=out, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(120):
        if proc.poll() is not None:
            out.close()
            raise RuntimeError('Isolated Java exited during startup')
        try:
            request('GET', '/task-workspaces')
            return proc, out
        except requests.RequestException:
            time.sleep(.5)
    proc.terminate(); proc.wait(timeout=25); out.close()
    raise RuntimeError('Isolated Java startup timeout')

def prevent_graph(facade):
    def submit(fn, *a, **kw):
        scheduled.append('execution explicitly suppressed')
        future = concurrent.futures.Future(); future.set_result(None)
        return future
    facade._executor.submit = submit

code = 1
try:
    facade = runtime.initialize_runtime(); prevent_graph(facade)
    thread.start()
    for _ in range(100):
        try:
            if session.get('http://127.0.0.1:8193/probe', timeout=1).status_code == 200:
                break
        except requests.RequestException:
            time.sleep(.1)
    else:
        raise RuntimeError('Isolated Python HTTP server startup timeout')
    process, log = start_java(1)
    assert request('GET', '/task-workspaces') == []
    task = request('POST', '/task-workspaces', {'id': 'publication-integration', 'title': '合成发布验收任务',
        'paperIds': [], 'messages': [], 'notes': [], 'artifacts': []}, status=201)
    start = {'requestId': 'synthetic-start', 'expectedTaskRevision': task['revision'], 'question': '合成发布测试，不执行研究生成',
        'sourcePolicy': {'mode': 'external_only'}, 'materialSelection': {'mode': 'external_only'},
        'budgetProfile': 'standard', 'outputKind': 'general'}
    started = request('POST', '/task-workspaces/publication-integration/research/start', start)
    rid = started['task']['runId']; record = facade._repo.require_run(rid)
    assert record['status'] == 'running'
    assert facade._repo.list_calls(rid) == []
    payload = {'reportVersionId': 'synthetic-v1', 'summary': '合成研究结果，仅验证发布链路。'}
    body = '合成研究报告：仅用于发布链路测试，不代表科学结论。'
    publication, created = facade._repo.publish_report(run_id=rid, dedup_key='synthetic-publish-v1', payload=payload,
        outcome='partial', report_text=body, expected_revision=record['runRevision'], expected_epoch=record['executionEpoch'])
    assert created
    def lost_ack(url, **kwargs):
        response = session.post(url, **kwargs)
        assert response.status_code == 200, response.text[:400]
        raise requests.ConnectionError('Simulated response loss after Java commit')
    lost = PublicationDispatcher(facade._repo, origin=base, post=lost_ack)
    assert lost.deliver_once() == 0
    saved = request('GET', '/task-workspaces/publication-integration')
    assert len(saved['artifacts']) == 2 and len(saved['messages']) == 1
    assert len(facade._repo.pending_publications()) == 1
    # A user can edit a report while its delivery acknowledgment is still
    # missing. An eventual duplicate must preserve this edit and provenance.
    edited = json.loads(json.dumps(saved))
    user_text = body + '\n\n合成用户修改：重投发布也应保留。'
    for artifact in edited['artifacts']:
        if artifact['origin'] == 'machine':
            artifact['text'] = '浏览器不得覆盖的原稿修改'
        else:
            artifact.update(text=user_text, edited=False, sourceRunId='forged-run', sourceResearchId='forged-run',
                reportVersionId='forged-version', paperIds=['forged-paper'], sources=[{'sourceId':'forged-source'}])
            artifact['versions'] = [{'text':body,'savedAt':'2026-11-12T00:00:00Z'}]
    saved = request('PUT', '/task-workspaces/publication-integration', edited)
    machine = next(a for a in saved['artifacts'] if a['origin'] == 'machine')
    latest = next(a for a in saved['artifacts'] if a['origin'] != 'machine')
    assert machine['text'] == body and latest['text'] == user_text and latest['edited'] is True
    assert latest['sourceRunId'] == latest['sourceResearchId'] == rid
    assert latest['reportVersionId'] == 'synthetic-v1' and latest['paperIds'] == latest['sources'] == []
    dispatcher = PublicationDispatcher(facade._repo, origin=base, post=session.post)
    assert dispatcher.deliver_once() == 1
    assert facade._repo.pending_publications() == []
    assert request('GET', '/task-workspaces/publication-integration') == saved
    assert dispatcher.deliver_once() == 0
    _, duplicate = facade._repo.publish_report(run_id=rid, dedup_key='synthetic-publish-v1', payload=payload,
        outcome='partial', report_text=body)
    assert not duplicate and facade._repo.pending_publications() == []
    assert request('GET', '/task-workspaces/publication-integration') == saved
    proof.update(lostAckPersistedInJava=True,duplicateDeliveryDidNotChangeTask=True,publicationReplayedWithoutNewOutbox=True,
        userEditBetweenDeliveriesPreserved=True,originalAndProvenanceProtectedThroughHttp=True,
        taskRevision=saved['revision'],artifactCount=2,messageCount=1,runId=rid)
    # Restart the production factory on the same isolated SQLite, keeping Java
    # and the HTTP router running; the dispatcher continues by stored engine.
    runtime.shutdown_runtime(); os.environ['DEEP_RESEARCH_V2_ENABLED'] = 'false'
    facade = runtime.initialize_runtime(); prevent_graph(facade)
    result = request('GET', f'/task-workspaces/publication-integration/research/{rid}')
    assert result['task']['report']['body'] == body
    assert result['task']['report']['versionId'] == 'synthetic-v1'
    assert 'continue' not in result['task']['allowedActions']
    current = request('GET', '/task-workspaces/publication-integration')
    request('POST', '/task-workspaces/publication-integration/research/start',
        {**start, 'requestId':'disabled-new', 'expectedTaskRevision':current['revision']}, status=503)
    assert len(facade._repo.list_runs()) == 1 and facade._repo.list_calls(rid) == []
    process.terminate(); process.wait(timeout=25); log.close(); process = log = None
    process, log = start_java(2)
    assert request('GET', '/task-workspaces/publication-integration') == current
    assert request('GET', f'/task-workspaces/publication-integration/research/{rid}')['task']['report']['body'] == body
    assert blocked == []
    proof.update(pythonRollbackRestartReadVerified=True,newEntryDisabledThroughJava=True,javaRestartPersistenceVerified=True,
        persistedModelCalls=0,suppressedWorkerCount=len(scheduled))
    code = 0
except Exception as error:
    proof['errorType'], proof['error'] = type(error).__name__, str(error)
finally:
    if process is not None and process.poll() is None:
        process.terminate(); process.wait(timeout=25)
    if log is not None:
        log.close()
    runtime.shutdown_runtime()
    server.should_exit = True
    if thread.is_alive():
        thread.join(timeout=15)
    requests.Session.send, requests.Session.__init__ = original_send, original_init
    proof.update(exitCode=code,pythonHttpStopped=not thread.is_alive(),javaStopped=process is None or process.poll() is not None,
        blockedRequests=blocked,httpRequests=http_log)
    with (root/'docs/deep-research-evidence'/('publication-integration-'+args.run_id+'.json')).open('x',encoding='utf8') as out:
        json.dump(proof,out,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in proof.items() if k!='httpRequests'},ensure_ascii=False))
raise SystemExit(code)
