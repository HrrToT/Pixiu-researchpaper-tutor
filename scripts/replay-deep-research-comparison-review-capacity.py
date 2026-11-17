"""Measure complete initial-review requests with saved drafts, no provider.

Alternative windows are offline prototypes. Empty review fixtures approve no
facts; reservation sums are upper bounds, not predicted provider consumption.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker
import services.deep_research.verification_capacity as capacity


def main(prefix, output):
    path = Path(str(prefix) + '.payload.json')
    raw = path.read_bytes()
    original = json.loads(raw)
    calls = json.loads(Path(str(prefix) + '.calls.json').read_text(encoding='utf-8-sig'))
    settled = [c for c in calls if c[2] == 'verify' and c[5] == 'succeeded']
    alternatives = []
    native_limit = capacity.verification_input_limit
    for window in (32000, 24000):
        r = deepcopy(original)
        r.update(status='running', startedAt=None)
        repo = DeepResearchRepository(ROOT / 'tmp' / ('comparison-review-capacity-' + uuid.uuid4().hex + '.sqlite3'))
        repo.initialize()
        repo.create_run(r)
        requests = []
        def reserve(**kw):
            requests.append({'node': kw['node'], 'argsDigest': kw['args_digest'],
                             'reservation': kw['budget_delta']})
            return {'result': {'content': '[]', 'finishReason': 'stop'}}, True
        client = Mock(spec=['invoke'])
        client.invoke.side_effect = AssertionError('Provider dispatch forbidden')
        invoke = TrackedLLMInvoker(client, reserve, repo.complete_call,
            run_record_fn=repo.require_run, call_history_fn=repo.list_calls,
            verification_max_input_bytes=32000, request_options=research_model_options)
        facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
        capacity.verification_input_limit = lambda record, node, legacy, configured: (
            min(window, native_limit(record, node, legacy, configured)) if node == 'verify'
            else native_limit(record, node, legacy, configured))
        try:
            semantic = facade._build_semantic_checker(r['runId'], invoke)
            result = facade._get_verify_claims(r['runId'])(r['state']['reportBody']['claims'],
                r['state']['evidence'], semantic)
        finally:
            capacity.verification_input_limit = native_limit
            facade.shutdown()
        client.invoke.assert_not_called()
        assert not result['accepted'] and not repo.list_calls(r['runId'])
        alternatives.append({'prototypeWindow': window, 'requests': requests,
            'callCount': len(requests), 'sumReservationUpperBounds': sum(x['reservation']['tokens'] for x in requests),
            'scientificApproval': False})
    assert path.read_bytes() == raw
    value = {'sourceReceiptSha256': hashlib.sha256(raw).hexdigest(), 'alternatives': alternatives,
        'observedSettledInitialReviews': [{'usage': json.loads(c[6]).get('usage'),
            'responseBytes': len(json.loads(c[6]).get('content', '').encode('utf8'))} for c in settled],
        'providerRequests': 0, 'liveLedgerMutations': 0,
        'boundary': 'Empty fixture decisions only. Window prototypes do not establish sequential cost, time, repair/final-audit capacity or quality.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-prefix', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    main(args.receipt_prefix, args.output)
