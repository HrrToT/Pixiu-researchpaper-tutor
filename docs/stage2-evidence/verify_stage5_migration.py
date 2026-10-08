"""Local storage acceptance only: never calls AI execution or retry endpoints."""
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
sys.stdout.reconfigure(encoding='utf-8')
base='http://localhost:8081/api/task-workspaces'
here=Path(__file__).parent

def http(path='', body=None):
    request=Request(base+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=20) as response: return json.load(response)

project_id='b1a9758b-d2d7-4fd5-999c-2427e8ad9585'
matching=[task for task in http() if (task.get('legacyMigration') or {}).get('projectId')==project_id]
assert len(matching)==1, 'Exactly one imported project task'
task=matching[0]
archive=task['legacyArchive']
server=http('/migrations/agent-projects/'+quote(project_id)+'/snapshot')['snapshot']
assert archive['serverSnapshot']==server, 'Complete original snapshot preserved'
reports=[item for item in task['artifacts'] if item.get('legacyRecord')]
assert len(reports)==1
assert reports[0]['text']==server['artifacts'][0]['draftReport']
assert len(reports[0]['sources'])==len(server['artifacts'][0].get('reportSources') or server['artifacts'][0].get('evidenceItems') or [])
backup=http('/'+quote(task['id'],safe='')+'/migration-backups/'+quote(task['legacyMigration']['backupId'],safe=''))
assert backup==archive
replay=http('/migrations/agent-projects', {'snapshot':archive,'task':task})
assert replay['status']=='already_imported' and replay['task']==task
files=list(Path('C:/Users/Lenovo/Downloads').glob('*LightGaussian*旧项目备份*.json'))
assert files, 'Browser download actually exists'
download=max(files,key=lambda path:path.stat().st_mtime)
assert json.loads(download.read_text(encoding='utf-8'))==archive
(here/'stage5-agent-backup-verified.json').write_text(json.dumps(archive,ensure_ascii=False,indent=2),encoding='utf-8')
result={'status':'passed','taskId':task['id'],'revision':task['revision'],'projectId':project_id,
    'papers':task['paperIds'],'reports':len(reports),'sources':len(reports[0]['sources']),
    'snapshotCounts':server['counts'],'replayNoWrite':True,'browserDownloadMatchesBackup':True,
    'materials':http('/'+quote(task['id'],safe='')+'/materials')}
(here/'stage5-agent-migration-runtime.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
