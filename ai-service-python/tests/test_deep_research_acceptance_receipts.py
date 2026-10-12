from concurrent.futures import ThreadPoolExecutor
import json
import pytest

from services.deep_research.acceptance_receipts import claim_submission, confirm_submission, read_receipt
from scripts.verify_deep_research_case import run_case


def test_exclusive_claim_and_unconfirmed_never_resubmits(tmp_path):
    path = tmp_path / 'case.json'
    def claim(_):
        try:
            claim_submission(path, {'question': '中文'})
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(8))) == 1
    assert read_receipt(path)['intent']['question'] == '中文'
    with pytest.raises(FileExistsError):
        claim_submission(path, {})


def test_confirmation_preserves_identity_and_other_lock(tmp_path):
    path = tmp_path / 'case.json'
    claim_submission(path, {})
    lock = tmp_path / 'case.json.lock'
    lock.write_text('another owner')
    with pytest.raises(FileExistsError):
        confirm_submission(path, 'run')
    assert lock.read_text() == 'another owner'
    lock.unlink()
    assert confirm_submission(path, 'run') == confirm_submission(path, 'run')
    with pytest.raises(ValueError):
        confirm_submission(path, 'different')
    assert read_receipt(path)['runId'] == 'run'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['case.json']


def test_invalid_intent_does_not_claim_and_invalid_receipt_fails(tmp_path):
    path = tmp_path / 'case.json'
    with pytest.raises(TypeError):
        claim_submission(path, {'value': object()})
    assert not path.exists()
    for value in [[], {}, {'schemaVersion': 1, 'intent': {}, 'submissionStatus': 'confirmed', 'runId': None}]:
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            read_receipt(path)


def manifest():
    return {'version': 1, 'frozenAt': 'date', 'budgetProfile': 'standard',
            'materials': {'p': {'sha256': 'hash'}}, 'cases': [{
                'id': 'D', 'split': 'development', 'kind': 'claim_verification',
                'question': 'A question', 'materials': ['p'], 'policy': 'task_only'}]}


def test_harness_preview_is_offline_and_confirmed_case_is_get_only(tmp_path):
    calls = []
    def api(method, path, **kwargs):
        calls.append((method, path))
        if path.endswith('/research/run') or path.endswith('/start'):
            return {'task': {'taskId': 'task', 'runId': 'run', 'status': 'completed', 'outcome': 'partial'}}
        return {'revision': 1, 'paperIds': ['hash.pdf']}
    assert run_case(manifest(), 'D', 1, tmp_path, api, task_id='task')['preview']
    assert not calls
    first = run_case(manifest(), 'D', 1, tmp_path, api, submit=True, task_id='task')
    assert first['outcome'] == 'partial'  # No automatic quality acceptance.
    calls.clear()
    run_case(manifest(), 'D', 1, tmp_path, api, submit=True, task_id='task')
    assert calls == [('GET', '/task-workspaces/task/research/run')]


def test_harness_ambiguous_submission_cannot_be_sent_again(tmp_path):
    calls = []
    def api(method, path, **kwargs):
        calls.append(method)
        if method == 'POST':
            raise TimeoutError('unknown response')
        return {'revision': 1, 'paperIds': ['hash.pdf']}
    with pytest.raises(TimeoutError):
        run_case(manifest(), 'D', 1, tmp_path, api, submit=True)
    assert calls == ['GET', 'POST']
    calls.clear()
    with pytest.raises(ValueError, match='unconfirmed'):
        run_case(manifest(), 'D', 1, tmp_path, api, submit=True)
    assert calls == []
