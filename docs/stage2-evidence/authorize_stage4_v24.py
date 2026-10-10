"""Verify the v24 runtime only after explicit approval has been recorded in its plan."""
import contextlib
import hashlib
import io
import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
path = HERE / 'stage4-analysis-v24-case-plan.json'
plan = json.loads(path.read_text(encoding='utf-8-sig'))
assert plan['status'] == 'authorized_pending_runtime' and plan.get('authorization')
assert plan['casesExecuted'] == 0 and plan['maxCases'] == 1
assert not (HERE / 'stage4-critique-v24-attempt.json').exists()
with contextlib.redirect_stdout(io.StringIO()):
    sys.argv = [str(HERE / 'verify_analysis_preservation_v19.py'), 'inspect']
    check = runpy.run_path(sys.argv[0], run_name='__main__')
report = check['report']
for version in ('v19', 'v22'):
    identity = 'stage4-3dgs-critique-20261010-' + version
    report['taskHashes'][version + '-critique'] = check['digest'](check['get']('/' + identity))
    report['receiptHashes'][version + '-critique'] = check['digest'](check['get'](f'/{identity}/operations/{identity}-request'))
baseline = json.loads((HERE / 'stage4-output-v23-final-reload-after.json').read_text(encoding='utf-8'))
assert report['taskHashes'] == baseline['taskHashes'] and report['receiptHashes'] == baseline['receiptHashes']
runtime = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .State}}',
    'ai_service_python'], text=True, encoding='utf-8'))
assert runtime['Running']
assert runtime['StartedAt'] == baseline['runningSince']
probe = '''import hashlib,json
from urllib.parse import urlsplit
from core.config import settings
from pathlib import Path
u=urlsplit(settings.deepseek_base_url)
names=['conversation_capability_service.py','grounded_numeric_rendering.py','grounded_critique.py']
print(json.dumps({'scheme':u.scheme,'hostname':u.hostname,'port':u.port,'model':settings.deepseek_model,
    'sourceHashes':{n:hashlib.sha256((Path('/app/services')/n).read_bytes()).hexdigest() for n in names}}))'''
actual = json.loads(subprocess.check_output(['docker', 'exec', 'ai_service_python', 'python', '-c', probe],
    text=True, encoding='utf-8'))
assert actual['scheme'] == 'https' and actual['hostname'] == 'api.deepseek.com' and actual['port'] in (None, 443)
assert actual['model'] == 'deepseek-v4-pro'
for name, digest in actual['sourceHashes'].items():
    assert digest == hashlib.sha256((ROOT / 'ai-service-python/services' / name).read_bytes()).hexdigest()
    committed = subprocess.check_output(['git', 'show',
        plan['sourceCommit'] + ':ai-service-python/services/' + name], cwd=ROOT)
    working = (ROOT / 'ai-service-python/services' / name).read_bytes()
    assert working.replace(b'\r\n', b'\n') == committed.replace(b'\r\n', b'\n')
    if name in baseline['sourceHashes']:
        assert digest == baseline['sourceHashes'][name]
with urlopen('http://127.0.0.1:8000/health', timeout=30) as response:
    assert json.load(response)['status'] == 'ok'
with urlopen('http://127.0.0.1:8081/api/task-workspaces/stage4-3dgs-critique-20261010-v22/materials/'
             + plan['materials'][0]['pdfId'] + '/processing', timeout=30) as response:
    assert json.load(response)['questionReady'] is True
verification = {'origin': plan['provider'], 'model': actual['model'], 'runningSince': runtime['StartedAt'],
                'sourceHashes': actual['sourceHashes']}
plan.update(status='authorized', authorizedAt=datetime.now(timezone.utc).isoformat(),
            providerOriginVerified=True, providerVerification=verification)
report.update(checkedAt=plan['authorizedAt'], runtimeVerification=verification,
              sourceCommitVerified=plan['sourceCommit'],
              baselineMissingSourceFields=sorted(set(actual['sourceHashes']) - set(baseline['sourceHashes'])),
              providerCalls=0, taskWrites=0)
with (HERE / 'stage4-analysis-v24-preservation-before.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'authorizedCases': 1, 'provider': plan['provider'], 'model': actual['model'],
                  'oldTasksUnchanged': 10, 'oldReceiptsUnchanged': 9, 'providerCalls': 0, 'taskWrites': 0}))
