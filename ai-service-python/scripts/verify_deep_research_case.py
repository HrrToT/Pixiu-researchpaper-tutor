"""Run one frozen acceptance case explicitly; existing receipts are GET-only.

Default invocation previews the case without HTTP. --submit permits a single
submission, not retries. A receipt with unknown outcome requires reconciliation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid
import re
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.deep_research.acceptance_receipts import claim_submission, confirm_submission, read_receipt, case_submission_lock
from services.deep_research.acceptance_manifest import require_frozen_case


def _prior_submission_identity(path, case_id, api=None):
    """Read receipt identities without trusting cached response/outcome fields.

    The original live harness used CASE.json and CASE-vN.json with top-level
    case/taskId/runId. Keep those files intact; they are history, not new intents.
    """
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Prior receipt schema is invalid; reconcile it before submitting.')
    if 'schemaVersion' in value or 'intent' in value:
        saved = read_receipt(path)
        identity, run_id = saved['intent'], saved['runId']
        recorded_case = identity.get('caseId')
    else:
        identity, run_id = value, value.get('runId')
        recorded_case = value.get('case')
    task_id = identity.get('taskId')
    if recorded_case != case_id or not isinstance(task_id, str) or not task_id.strip():
        raise ValueError('Prior receipt identity is invalid; reconcile it before submitting.')
    if run_id is None:
        from services.deep_research.legacy_action_reconciliation import resolution_path, require_live_legacy_resolution
        if api is not None and resolution_path(path).exists():
            require_live_legacy_resolution(path,case_id,api)
            return task_id,None  # This exact pre-child failure created no run.
        raise ValueError('Prior submission is unconfirmed; reconcile it before any new attempt.')
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('Prior run identity is invalid; reconcile it before submitting.')
    return task_id, run_id


def require_previous_cases_settled(directory, case_id, api, *, history_directories=()):
    """Check authoritative prior state before a new attempt can mutate anything.

    Local result snapshots may be stale. Changing attempt or task IDs must not
    bypass an unconfirmed submission, active run or unresolved outcome.
    """
    pattern = re.compile(re.escape(case_id) + r'(?:-v[0-9]+)?\.json')
    directories = dict.fromkeys(Path(p).resolve() for p in (directory, *history_directories))
    identities = {}
    for folder in directories:
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if not pattern.fullmatch(path.name):
                continue
            task_id, run_id = _prior_submission_identity(path, case_id, api)
            if run_id is None:
                continue  # Reconciled specific pre-child failure, never a provider unknown.
            if run_id in identities and identities[run_id] != task_id:
                raise ValueError('Conflicting prior run identities; reconcile before submitting.')
            identities[run_id] = task_id
    for run_id, task_id in identities.items():
        old_path = '/task-workspaces/' + quote(task_id, safe='') + '/research/' + quote(run_id, safe='')
        state = api('GET', old_path)['task']
        if state.get('runId') != run_id or state.get('taskId') != task_id:
            raise ValueError('Prior run identity mismatch')
        # Cancellation alone does not reconcile a potentially billed request.
        if state.get('status') not in {'completed', 'failed'} or state.get('errorCode') == 'unresolved_unknown':
            raise ValueError('Prior attempt has no confirmed terminal outcome; do not bypass it with a new attempt.')


def run_case(manifest, case_id, attempt, directory, api, *, submit=False,
             task_id=None, parent_run_id=None, check_ready=None,
             history_directories=(), lock_directory=None):
    if attempt < 1:
        raise ValueError('attempt must be positive')
    case = next((c for c in manifest['cases'] if c['id'] == case_id), None)
    if not case or not case.get('question'):
        raise ValueError('Select a model case; fault-injection cases use offline tests.')
    require_frozen_case(manifest, case)
    if case.get('mode') == 'continuation' and not (parent_run_id and task_id):
        raise ValueError('Continuation needs an existing task and parent run.')
    materials = [manifest['materials'][key]['sha256'] + '.pdf' for key in case['materials']]
    task_id = task_id or f"dr-acceptance-{case_id.lower()}-{manifest['frozenAt']}"
    intent = {'caseId': case_id, 'split': case['split'], 'attempt': attempt,
              'taskId': task_id, 'parentRunId': parent_run_id, 'question': case['question'],
              'materialIds': materials, 'outputKind': case['kind'], 'sourcePolicy': case['policy'],
              'budgetProfile': manifest['budgetProfile'], 'manifestVersion': manifest['version']}
    receipt = Path(directory) / f'{case_id}-v{attempt}.json'
    task_path = '/task-workspaces/' + quote(task_id, safe='')
    if receipt.exists():
        saved = read_receipt(receipt)
        if saved['intent'] != intent:
            raise ValueError('Receipt belongs to different inputs; do not reuse this attempt.')
        if not saved['runId']:
            raise ValueError('Submission outcome is unconfirmed; reconcile it before any new request.')
    elif not submit:
        return {'preview': True, 'intent': intent}
    else:
        if lock_directory is not None and Path(directory).resolve() != Path(lock_directory).resolve():
            raise ValueError('New submissions require the canonical receipt directory; custom folders are read-only.')
        if check_ready is not None:
            check_ready()  # Before workspace mutations or durable submission intent.
        with case_submission_lock(lock_directory or directory, case_id):
            require_previous_cases_settled(directory, case_id, api, history_directories=history_directories)
            task = api('GET', task_path, allow_missing=True)
            if task is None:
                if parent_run_id:
                    raise ValueError('Parent task is missing')
                task = api('POST', '/task-workspaces', payload={
                    'id': task_id, 'title': '深度研究验收 · ' + case_id,
                    'paperIds': materials, 'focusedPaperId': materials[0] if materials else None,
                    'notes': [], 'messages': [], 'artifacts': [], 'researchRuns': []})
            if not set(materials) <= set(task.get('paperIds', [])):
                raise ValueError('Frozen case materials are missing from this task')
            request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(intent, sort_keys=True, ensure_ascii=False)))
            payload = {'requestId': request_id, 'question': case['question'],
                       'budgetProfile': manifest['budgetProfile']}
            if parent_run_id:
                parent_path = task_path + '/research/' + quote(parent_run_id, safe='')
                parent = api('GET', parent_path)['task']
                if parent.get('taskId') != task_id or parent.get('runId') != parent_run_id:
                    raise ValueError('Parent identity mismatch')
                payload['expectedRunRevision'] = parent['runRevision']
                path = parent_path + '/continue'
            else:
                payload.update(engineVersion='deep-research-v2', contractVersion=2,
                               expectedTaskRevision=task['revision'],
                               materialSelection={'mode': 'explicit' if materials else 'external_only', 'materialIds': materials},
                               focusPaperIds=materials[:1] if case['kind'] == 'claim_verification' else [],
                               sourcePolicy={'mode': case['policy']}, outputKind=case['kind'])
                path = task_path + '/research/start'
            claim_submission(receipt, intent)  # Durable exclusive intent BEFORE model-capable POST.
            result = api('POST', path, payload=payload)
            state = result['task']
            if state.get('taskId') != task_id:
                raise ValueError('Returned task identity mismatch; receipt remains unconfirmed')
            saved = confirm_submission(receipt, state['runId'])
    result = api('GET', task_path + '/research/' + quote(saved['runId'], safe=''))
    state = result.get('task', {})
    if state.get('runId') != saved['runId'] or state.get('taskId') != task_id:
        raise ValueError('Read identity mismatch')
    receipt.with_suffix('.result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'caseId': case_id, 'runId': saved['runId'], 'status': state.get('status'),
            'outcome': state.get('outcome'), 'budget': state.get('budget'), 'error': state.get('error')}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case')
    parser.add_argument('--attempt', type=int, default=1)
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--manifest', type=Path, default=root / 'docs/DEEP_RESEARCH_ACCEPTANCE_CASES_20261012.json')
    parser.add_argument('--receipts', type=Path, default=root / 'tmp/dr-acceptance-receipts',
                        help='Existing receipt folder; new submissions use the canonical repository folder.')
    parser.add_argument('--origin', default='http://127.0.0.1:8081/api')
    parser.add_argument('--ai-origin', default='http://127.0.0.1:8000')
    parser.add_argument('--task-id')
    parser.add_argument('--parent-run-id')
    args = parser.parse_args()
    import requests
    def check_ready():
        response = requests.get(args.ai_origin.rstrip('/') + '/health', timeout=(3, 15))
        response.raise_for_status()
        require_ready_health(response.json())
    def api(method, path, *, payload=None, allow_missing=False):
        response = requests.request(method, args.origin.rstrip('/') + path, json=payload, timeout=25)
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    canonical_receipts = root / 'tmp/dr-acceptance-receipts'
    history_directories = [canonical_receipts]
    legacy_history = manifest.get('review', {}).get('rawReceiptDirectory')
    if legacy_history:
        legacy_history = Path(legacy_history)
        history_directories.append(legacy_history if legacy_history.is_absolute() else root / legacy_history)
    result = run_case(manifest, args.case, args.attempt,
                      args.receipts, api, submit=args.submit, task_id=args.task_id,
                      parent_run_id=args.parent_run_id, check_ready=check_ready,
                      history_directories=history_directories, lock_directory=canonical_receipts)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def require_ready_health(health):
    if (not isinstance(health, dict) or health.get('status') != 'ok'
            or not isinstance(health.get('checks'), dict)
            or any(not isinstance(health['checks'].get(name), dict)
                   or health['checks'][name].get('status') != 'ok' for name in ('rag', 'grobid'))):
        raise RuntimeError('AI service is not ready; no case submitted. Check API, RAG and GROBID.')


if __name__ == '__main__':
    main()
