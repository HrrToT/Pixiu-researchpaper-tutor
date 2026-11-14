from pathlib import Path
import os,json,time,subprocess,socket,urllib.request,hashlib,argparse,re
parser=argparse.ArgumentParser(description='Opt-in synthetic artifact persistence verification; owns isolated Java/H2 and Vite ports.')
parser.add_argument('--java',required=True,type=Path)
parser.add_argument('--jar',required=True,type=Path)
parser.add_argument('--run-id',required=True)
args=parser.parse_args()
assert re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id),'Invalid run ID'
root=Path(__file__).resolve().parents[1]; work=root/'tmp'/('isolated-persistence-'+args.run_id); work.mkdir(exist_ok=False)
java=args.java.resolve(strict=True)
jar=args.jar.resolve(strict=True)
for port in [8187,4274]:
    with socket.socket() as s: assert s.connect_ex(('127.0.0.1',port))!=0, 'Port occupied'
url='http://127.0.0.1:8187/api/task-workspaces'
def read():
    with urllib.request.urlopen(url,timeout=2) as r:return json.load(r)
def start(index):
    log=(work/f'java-{index}.log').open('x',encoding='utf8')
    p=subprocess.Popen([str(java),'-jar',str(jar),'--server.address=127.0.0.1','--server.port=8187',
      '--spring.datasource.url=jdbc:h2:file:./db/acceptance;DB_CLOSE_ON_EXIT=FALSE',
      '--PYTHON_URL=http://127.0.0.1:1/api'],cwd=work,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (work/f'java-{index}-pid.json').write_text(json.dumps({'pid':p.pid}),encoding='utf8')
    for _ in range(120):
        if p.poll() is not None: raise RuntimeError('Java terminated; inspect log')
        try: read(); return p,log
        except Exception:time.sleep(.5)
    p.terminate();p.wait(timeout=20);log.close();raise RuntimeError('Java startup timeout')
config=root/'frontend/tmp'/('isolated-persistence-'+args.run_id+'.config.mjs'); config.parent.mkdir(exist_ok=True); assert not config.exists()
report=work/'playwright.json'
config.write_text("import {defineConfig,devices} from '@playwright/test';export default defineConfig("+json.dumps({
  'testDir':(root/'frontend/tests/e2e').as_posix(),'workers':1,'retries':0,'timeout':60000,
  'reporter':[['list'],['json',{'outputFile':report.as_posix()}]],'outputDir':(work/'browser').as_posix(),
  'use':{'baseURL':'http://127.0.0.1:4274','headless':True,'screenshot':'only-on-failure','trace':'retain-on-failure'},
  'webServer':{'command':'npm run dev -- --host 127.0.0.1 --port 4274 --strictPort','cwd':(root/'frontend').as_posix(),'url':'http://127.0.0.1:4274','reuseExistingServer':False,'timeout':120000}
})+");",encoding='utf8')
p=None;log=None;code=1;proof={'newModelCalls':0,'productionWrites':0,'isolatedDatabase':str(work/'db/acceptance'),
 'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'javaPort':8187,'vitePort':4274,
 'boundary':'Actual Java artifact persistence; no Python research/model invocation; synthetic user-authored note, not research provenance.'}
try:
    p,log=start(1)
    assert read()==[]
    env=os.environ.copy();env['VITE_API_BASE_URL']='/api';env['VITE_AGENT_API_BASE_URL']='/api';env['PIXIU_ISOLATED_PERSISTENCE_URL']='http://127.0.0.1:8187'
    with (work/'browser.log').open('x',encoding='utf8') as out:
        result=subprocess.run(['node',str(root/'frontend/node_modules/@playwright/test/cli.js'),'test','task-persistence-live.spec.js','--config',str(config)],cwd=root/'frontend',env=env,stdout=out,stderr=subprocess.STDOUT)
    proof['browserExitCode']=result.returncode
    if result.returncode: raise RuntimeError('Browser test failed')
    before=read();p.terminate();p.wait(timeout=25);log.close();p=None;log=None
    p,log=start(2);after=read()
    assert before==after and len(after)==1
    proof.update(restartPersistenceVerified=True,taskCount=1,taskRevision=after[0]['revision'],historyVersions=len(after[0]['artifacts'][0]['versions']))
    code=0
except Exception as error:proof['error']=str(error)
finally:
    if p is not None and p.poll() is None:p.terminate();p.wait(timeout=25)
    if log:log.close()
    proof['ownedJavaStopped']=p is None or p.poll() is not None
    if report.exists():proof['browserStats']=json.loads(report.read_text(encoding='utf8'))['stats']
    proof['exitCode']=code
    with (root/'docs/deep-research-evidence'/('frontend-live-persistence-'+args.run_id+'.json')).open('x',encoding='utf8') as f:json.dump(proof,f,ensure_ascii=False,indent=2)
    print(json.dumps(proof,ensure_ascii=False))
raise SystemExit(code)



