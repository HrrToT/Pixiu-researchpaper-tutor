"""Restore known project backups into a new isolated directory; never replace live data.

Java reads the H2 backup using a supplied rollback JAR. The current durable
Python executor retains historical contracts with new-run rollout disabled.
Workers and publication delivery are forbidden; this is a restore/read drill.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,socket,sqlite3,subprocess,sys,threading,time,traceback
from urllib.parse import urlparse

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--java',required=True,type=Path)
parser.add_argument('--jar',required=True,type=Path)
parser.add_argument('--h2-backup',required=True,type=Path)
parser.add_argument('--baseline',required=True,type=Path)
parser.add_argument('--run-id',required=True)
args=parser.parse_args()
assert re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id)
root=Path(__file__).resolve().parents[1]
work=root/'tmp'/('backup-restore-'+args.run_id)
java,jar,h2=args.java.resolve(strict=True),args.jar.resolve(strict=True),args.h2_backup.resolve(strict=True)
baseline=json.loads(args.baseline.read_text(encoding='utf8'))
for port in (8186,8195):
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',port))!=0,'Isolated port occupied'
work.mkdir(exist_ok=False);(work/'db').mkdir()
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
copied_h2=work/'db/academic_db.mv.db';shutil.copy2(h2,copied_h2)
assert sha(copied_h2)==sha(h2)==baseline['java']['h2BackupSha256'].lower()
sqlite_copy=work/'research.sqlite3'
subprocess.run(['docker','cp','academic-dr-runtime:/research_data/backups/service-load-20261112/research.sqlite3',str(sqlite_copy)],check=True,capture_output=True)
expected=next(v['sha256'] for v in baseline['attestation']['sqliteBackups'] if v['file']=='research.sqlite3')
assert sha(sqlite_copy)==expected
def database():
    db=sqlite3.connect('file:'+str(sqlite_copy)+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    tables={}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'deep_research_%' ORDER BY name"):
        assert name.replace('_','').isalnum();h=hashlib.sha256();count=0
        for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid'):
            h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n');count+=1
        tables[name]={'rows':count,'sha256':h.hexdigest()}
    db.close();return tables
assert database()==baseline['research']['tables']
sys.path.insert(0,str(root/'ai-service-python'))
os.environ.update(DEEP_RESEARCH_V2_ENABLED='false',DEEP_RESEARCH_EXTERNAL_ENABLED='false',
    DEEP_RESEARCH_DB_PATH=str(sqlite_copy),DEEP_RESEARCH_JAVA_ORIGIN='http://127.0.0.1:8186/api')
import requests,uvicorn
from fastapi import FastAPI
from services.deep_research import runtime
from services.deep_research.publication import PublicationDispatcher
from routes.research_routes import research_router
blocked=[];original_send,original_init=requests.Session.send,requests.Session.__init__
def session_init(self,*a,**kw):original_init(self,*a,**kw);self.trust_env=False
def send(self,request,**kwargs):
    url=urlparse(request.url)
    if url.hostname!='127.0.0.1' or url.port not in (8186,8195):
        blocked.append(request.url);raise AssertionError('Non-isolated request blocked')
    return original_send(self,request,**kwargs)
requests.Session.__init__,requests.Session.send=session_init,send
class ForbiddenModel:
    def invoke(self,*a,**kw):blocked.append('model');raise AssertionError('No model permitted')
runtime.research_model=lambda:ForbiddenModel()
PublicationDispatcher.start=lambda self:None
app=FastAPI();app.include_router(research_router,prefix='/api')
@app.get('/probe')
def probe():return {'isolated':True}
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8195,log_level='error',access_log=False))
thread=threading.Thread(target=server.run,daemon=True)
session=requests.Session();process=log=None;code=1
proof={'liveDatabasesReplaced':False,'productionWrites':0,'modelCalls':0,'h2BackupSha256':sha(h2),'sqliteBackupSha256':expected,
 'rollbackJarSha256':sha(jar),'pythonPolicy':'Current durable executor, original run contracts, rollout disabled',
 'boundary':'Backup restoration and isolated read compatibility; not live production rollback or research quality acceptance'}
try:
    facade=runtime.initialize_runtime()
    def forbid_worker(*a,**kw):blocked.append('worker');raise AssertionError('No historical execution permitted')
    facade._executor.submit=forbid_worker
    thread.start()
    for _ in range(100):
        try:
            if session.get('http://127.0.0.1:8195/probe',timeout=1).status_code==200:break
        except requests.RequestException:time.sleep(.1)
    else:raise RuntimeError('Isolated Python startup failed')
    log=(work/'java.log').open('x',encoding='utf8')
    process=subprocess.Popen([str(java),'-Xmx384m','-jar',str(jar),'--server.address=127.0.0.1','--server.port=8186',
        '--spring.datasource.url=jdbc:h2:file:./db/academic_db;DB_CLOSE_ON_EXIT=FALSE',
        '--PYTHON_URL=http://127.0.0.1:8195/api'],cwd=work,stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('Rollback Java exited')
        try:
            response=session.get('http://127.0.0.1:8186/api/task-workspaces',timeout=2);response.raise_for_status();tasks=response.json();break
        except requests.RequestException:time.sleep(.5)
    else:raise RuntimeError('Rollback Java readiness failed')
    assert {t['id']:digest(t) for t in tasks}==baseline['taskSha256']
    # Do not materialize all historical state/evidence payloads or rely on the
    # repository's default 200-row page. Identity enumeration is lightweight.
    with sqlite3.connect('file:'+str(sqlite_copy)+'?mode=ro',uri=True) as db:
        identities=db.execute('SELECT run_id,status FROM deep_research_runs_v2 ORDER BY rowid').fetchall()
    assert len(identities)==baseline['research']['tables']['deep_research_runs_v2']['rows']
    paused=[rid for rid,status in identities if status=='paused']
    assert len(paused)==baseline['research']['statuses']['paused']
    for rid in paused:
        view=facade.get(rid)
        assert view['status']=='paused' and 'resume' not in view['allowedActions'] and 'continue' not in view['allowedActions']
    # Only query a report already applied to Java with the exact current version.
    checked=None
    for task in tasks:
        for artifact in task.get('artifacts',[]):
            rid=artifact.get('sourceRunId');version=artifact.get('reportVersionId')
            if not rid or not version or f'v2-research:{rid}:{version}' not in task.get('appliedRequestIds',[]):continue
            record=facade._repo.get_run(rid)
            if not record:continue
            report=facade.get(rid).get('report')
            if not report or report.get('versionId')!=version:continue
            response=session.get(f"http://127.0.0.1:8186/api/task-workspaces/{task['id']}/research/{rid}",timeout=15);response.raise_for_status();result=response.json()
            assert result['task']['report']['body']==report['body']
            assert digest(result['workspace'])==baseline['taskSha256'][task['id']]
            checked={'runId':rid,'reportVersionId':version,'bodySha256':digest(report['body'])};break
        if checked:break
    assert checked
    final=session.get('http://127.0.0.1:8186/api/task-workspaces',timeout=15).json()
    assert {t['id']:digest(t) for t in final}==baseline['taskSha256']
    assert database()==baseline['research']['tables'] and blocked==[]
    assert sha(h2)==baseline['java']['h2BackupSha256'].lower()
    proof.update(taskCount=len(tasks),runCount=len(identities),pausedUnknownCount=len(paused),allTasksPreserved=True,
        allResearchTablesPreserved=True,unknownRunsNotResumed=True,restoredReport=checked,blockedRequests=blocked)
    code=0
except Exception as error:proof.update(errorType=type(error).__name__,error=str(error),traceback=traceback.format_exc())
finally:
    if process is not None and process.poll() is None:process.terminate();process.wait(timeout=25)
    if log:log.close()
    runtime.shutdown_runtime();server.should_exit=True
    if thread.is_alive():thread.join(timeout=15)
    requests.Session.send,requests.Session.__init__=original_send,original_init
    proof.update(exitCode=code,isolatedPythonStopped=not thread.is_alive(),isolatedJavaStopped=process is None or process.poll() is not None)
    with (root/'docs/deep-research-evidence'/('backup-restore-'+args.run_id+'.json')).open('x',encoding='utf8') as out:json.dump(proof,out,ensure_ascii=False,indent=2)
    print(json.dumps(proof,ensure_ascii=False))
raise SystemExit(code)
