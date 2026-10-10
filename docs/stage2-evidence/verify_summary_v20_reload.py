"""Record task/receipt preservation around the summary-only service reload."""
import contextlib
import io
import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).parent
mode = sys.argv[1]
assert mode in {'before', 'after'}
sys.argv = [str(HERE / 'verify_analysis_preservation_v19.py'), 'inspect']
with contextlib.redirect_stdout(io.StringIO()):
    check = runpy.run_path(sys.argv[0], run_name='__main__')
report = check['report']
v19task = check['get']('/stage4-3dgs-critique-20261010-v19')
v19receipt = check['get']('/stage4-3dgs-critique-20261010-v19/operations/stage4-3dgs-critique-20261010-v19-request')
assert v19receipt['status'] == 'succeeded' and v19receipt['result']['partial']
assert len(v19task['artifacts']) == 1
report['taskHashes']['v19-critique'] = check['digest'](v19task)
report['receiptHashes']['v19-critique'] = check['digest'](v19receipt)
report.update(mode=mode, checkedAt=datetime.now(timezone.utc).isoformat(), codeCommit='643ba9e')
report['runningSince'] = subprocess.check_output(['docker', 'inspect', '--format',
    '{{.State.StartedAt}}', 'ai_service_python'], text=True).strip()
if mode == 'after':
    baseline = json.loads((HERE / 'stage4-summary-v20-preservation-before.json').read_text(encoding='utf-8'))
    assert report['taskHashes'] == baseline['taskHashes']
    assert report['receiptHashes'] == baseline['receiptHashes']
    assert report['runningSince'] > baseline['runningSince']
    source_hash = subprocess.check_output(['docker', 'exec', 'ai_service_python', 'python', '-c',
        'import hashlib,inspect; from services.conversation_capability_service import _critique; '
        'print(hashlib.sha256(open(inspect.getsourcefile(_critique), "rb").read()).hexdigest())'], text=True).strip()
    import hashlib
    assert source_hash == hashlib.sha256((HERE.parent.parent / 'ai-service-python/services/conversation_capability_service.py').read_bytes()).hexdigest()
    report['sourceSha256'] = source_hash
    with urlopen('http://127.0.0.1:8000/health', timeout=30) as response:
        report['health'] = json.load(response)
    assert report['health']['status'] == 'ok'
with (HERE / f'stage4-summary-v20-preservation-{mode}.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps({'mode': mode, 'taskCount': len(report['taskHashes']),
    'receiptCount': len(report['receiptHashes']), 'runningSince': report['runningSince'],
    'providerCalls': 0, 'taskWrites': 0}))
