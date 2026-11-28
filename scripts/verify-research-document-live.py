"""Isolated Java/H2 + real browser publication of an explicitly synthetic report.

The upstream is a loopback fixture server, not a research engine or model. No
production task, paper, database, credential or unknown request is used.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse, hashlib, json, os, socket, subprocess, threading, time, urllib.request, urllib.error

ROOT=Path(__file__).resolve().parents[1]
TASK='isolated-shared-report';RUN='dr_run_synthetic_shared_report'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);args=parser.parse_args()
    if not args.run_id.replace('-','').isalnum():parser.error('Use a plain unique run id')
    work=ROOT/'tmp'/args.run_id;work.mkdir(exist_ok=False)
    java=ROOT/'tmp/jdk21-dr153/jdk-21.0.12.1+1/bin/java.exe'
    jar=ROOT/'backend-java/target/backend-java-0.0.1-SNAPSHOT.jar'
    fixture=json.loads((ROOT/'frontend/src/components/__fixtures__/sharedExperimentReport.json').read_text(encoding='utf-8'))
    java_port,vite_port,upstream_port=8188,4275,8769
    for port in (java_port,vite_port,upstream_port):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Isolated port is already occupied')
    base=f'http://127.0.0.1:{java_port}';calls=[]
    state={'contractVersion':2,'engineVersion':'deep-research-v2','taskId':TASK,'runId':RUN,
        'runRevision':1,'status':'queued','outcome':'none','title':'实验方案持久化演练','outputKind':'experiment_design'}
    sources=deepcopy(fixture['sources'])
    sources[0].update(sourceId='synthetic-source',sourceKind='external')
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,status=200):
            raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            calls.append({'method':'GET','path':self.path})
            if self.path=='/api/research-tasks/capabilities':return self.reply({'enabled':True,'externalSearch':True})
            if self.path=='/api/research-tasks/'+RUN:return self.reply({'status':'success','task':state})
            if self.path=='/api/task-operations/'+TASK:return self.reply([])
            calls[-1]['unexpected']=True
            self.reply({'message':'Unexpected fixture route'},501)
        def do_POST(self):
            if self.headers.get('Transfer-Encoding','').lower()=='chunked':
                chunks=[]
                while True:
                    size=int(self.rfile.readline().split(b';',1)[0].strip(),16)
                    if size==0:
                        while self.rfile.readline().strip():pass
                        break
                    if size<0 or sum(map(len,chunks))+size>100000:raise ValueError('Fixture body limit')
                    chunks.append(self.rfile.read(size))
                    if self.rfile.read(2)!=b'\r\n':raise ValueError('Invalid chunk delimiter')
                raw=b''.join(chunks)
            else:raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
            body=json.loads(raw or '{}')
            calls.append({'method':'POST','path':self.path,'bodyKeys':sorted(body),
                          'contentLength':self.headers.get('Content-Length'),'transferEncoding':self.headers.get('Transfer-Encoding')})
            if self.path=='/api/research-tasks':
                if body.get('workspaceTaskId')!=TASK:return self.reply({'message':'Wrong isolated owner'},400)
                return self.reply({'status':'success','task':state})
            if self.path=='/api/research-tasks/'+RUN+'/resume':
                state.update(status='completed',outcome='complete',runRevision=2,
                    summary='人工样本：只验证发布与持久化，不是科学研究结果。',reportVersionId='synthetic-v1',
                    report={'versionId':'synthetic-v1','body':fixture['report'],'origin':'machine'},
                    sources=sources,sourceCount=1,allowedActions=['continue'],plan=[],events=[])
                return self.reply({'status':'success','task':state})
            calls[-1]['unexpected']=True;self.reply({'message':'No model or other action is available'},501)
    server=ThreadingHTTPServer(('127.0.0.1',upstream_port),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def request(path,body=None):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            (work/'http-error.json').write_text(json.dumps({'path':path,'status':exc.code,
                'response':exc.read().decode('utf-8',errors='replace')},ensure_ascii=False,indent=2),encoding='utf-8')
            raise
    def start(index):
        log=(work/f'java-{index}.log').open('x',encoding='utf-8')
        process=subprocess.Popen([str(java),'-jar',str(jar),'--server.address=127.0.0.1',f'--server.port={java_port}',
            '--spring.datasource.url=jdbc:h2:file:./db/acceptance;DB_CLOSE_ON_EXIT=FALSE',
            f'--PYTHON_URL=http://127.0.0.1:{upstream_port}/api'],cwd=work,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        (work/f'java-{index}-pid.json').write_text(json.dumps({'pid':process.pid}),encoding='utf-8')
        for _ in range(120):
            if process.poll() is not None:raise RuntimeError('Isolated Java terminated; inspect log')
            try:request('/api/task-workspaces');return process,log
            except Exception:time.sleep(.5)
        process.terminate();process.wait(timeout=20);log.close();raise RuntimeError('Isolated Java startup not observed')
    process=log=None;code=1
    proof={'boundary':'Synthetic upstream + actual Java publication/H2/browser; no scientific or model quality credit',
        'runId':args.run_id,'productionWrites':0,'modelRequests':0,'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest()}
    try:
        process,log=start(1)
        if request('/api/task-workspaces')!=[]:raise RuntimeError('Expected empty isolated database')
        task=request('/api/task-workspaces',{'id':TASK,'title':'独立研究成果演练','paperIds':[],
            'messages':[],'notes':[],'artifacts':[],'researchRuns':[]})
        request('/api/task-workspaces/'+TASK+'/research/start',{'requestId':'synthetic-start','expectedTaskRevision':task['revision'],
            'question':'设计一个2×2实验（人工接口样本）','outputKind':'experiment_design',
            'materialSelection':{'mode':'external_only'},'sourcePolicy':{'mode':'external_only'},'budgetProfile':'standard'})
        request('/api/task-workspaces/'+TASK+'/research/'+RUN)
        published=request('/api/task-workspaces/'+TASK)
        if len(published['artifacts'])!=2:raise RuntimeError('Expected immutable and editable published versions')
        config=work/'playwright.config.mjs';report=work/'playwright.json'
        config.write_text("import {defineConfig} from "+json.dumps((ROOT/'frontend/node_modules/@playwright/test/index.mjs').as_posix())+";export default defineConfig("+json.dumps({
            'testDir':(ROOT/'frontend/tests/e2e').as_posix(),'workers':1,'retries':0,'timeout':90000,
            'reporter':[['list'],['json',{'outputFile':report.as_posix()}]],'outputDir':(work/'browser').as_posix(),
            'use':{'baseURL':f'http://127.0.0.1:{vite_port}','headless':True,'trace':'retain-on-failure'},
            'webServer':{'command':f'npm run dev -- --host 127.0.0.1 --port {vite_port} --strictPort','cwd':str(ROOT/'frontend'),
                'url':f'http://127.0.0.1:{vite_port}','reuseExistingServer':False,'timeout':120000}})+");",encoding='utf-8')
        env=os.environ.copy();env.update(PIXIU_ISOLATED_RESEARCH_URL=base,VITE_API_BASE_URL='/api',VITE_AGENT_API_BASE_URL='/api')
        with (work/'browser.log').open('x',encoding='utf-8') as browser_log:
            browser=subprocess.run(['node',str(ROOT/'frontend/node_modules/@playwright/test/cli.js'),'test',
                'research-document-live.spec.js','--config',str(config)],cwd=ROOT/'frontend',env=env,stdout=browser_log,stderr=subprocess.STDOUT)
        if browser.returncode:raise RuntimeError('Browser test failed; inspect saved trace')
        if any(c.get('unexpected') for c in calls):raise RuntimeError('Unexpected synthetic upstream request')
        before=request('/api/task-workspaces');process.terminate();process.wait(timeout=25);log.close();process=log=None
        process,log=start(2);after=request('/api/task-workspaces')
        if before!=after:raise RuntimeError('State changed across isolated Java restart')
        proof.update(browserPassed=True,restartPersistenceVerified=True,taskCount=len(after))
        code=0
    except Exception as exc:proof['errorType']=type(exc).__name__;proof['error']=str(exc)
    finally:
        if process is not None and process.poll() is None:process.terminate();process.wait(timeout=25)
        if log:log.close()
        server.shutdown();server.server_close()
        proof.update(exitCode=code,ownedJavaStopped=process is None or process.poll() is not None,fixtureUpstreamCalls=calls)
        (work/'receipt.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(proof,ensure_ascii=False),flush=True)
    raise SystemExit(code)


if __name__=='__main__':main()
