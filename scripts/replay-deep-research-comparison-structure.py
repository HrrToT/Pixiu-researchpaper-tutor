"""Compare stage isolation and stable recheck windows without provider requests.

Uses actual graph/checker/invoker code with isolated SQLite and explicit null
fixtures. Reservation previews do not prove sequential provider cost or quality.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import subprocess
from unittest.mock import Mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))
from services.deep_research.graph import make_synthesize_node
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.runtime import research_model_options
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
import services.deep_research.comparison_stage_inputs as stage_inputs
import services.deep_research.verification_capacity as capacity


def packet(prompt):
    text = prompt.split('Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n', 1)[1]
    value = json.JSONDecoder().raw_decode(text)[0]
    return untables(unpack(value)) if set(value) == {'strings', 'value'} else value


def main(prefix, output, generation_only=False):
    path = Path(str(prefix) + '.payload.json')
    raw = path.read_bytes()
    original = json.loads(raw)
    calls = json.loads(Path(str(prefix) + '.calls.json').read_text(encoding='utf-8-sig'))
    models = [c for c in calls if c[3] == 'llm_invoke']
    before = models[:next(i for i, c in enumerate(models) if c[2] == 'synthesize')]
    native_prepare = stage_inputs.prepare
    stage_results = []
    for merged, stage_window, profile in ((True, 32000, 1), (False, 32000, 1),
                                         (False, 24000, 1), (True, 32000, 2), (True, 32000, 3)):
        r = deepcopy(original)
        r.update(status='running', startedAt=None)
        r['comparisonAuthoringContractVersion'] = profile
        r['budget'].update(modelCalls=sum(not c[12] for c in before), reservedModelCalls=sum(bool(c[12]) for c in before),
            tokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in before),
            normalTokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in before if not c[12]), elapsedSeconds=0)
        for key in list(r['state']):
            if key.startswith(('repair', 'publication', 'verified', 'comparison', 'synthesis', 'report')) \
                    or key in ('initialVerification', 'initialAnswerCoverage', 'draftValidationAudit', 'factualDraftingAudit'):
                r['state'].pop(key)
        repo = DeepResearchRepository(ROOT / 'tmp' / ('comparison-isolation-' + uuid.uuid4().hex + '.sqlite3'))
        repo.initialize()
        repo.create_run(r)
        def prepare(*args, **kw):
            return native_prepare(*args, **{**kw, 'merge_joint': merged, 'max_input_bytes': stage_window})
        def fixture(rid, node, prompt, options, **kw):
            data = packet(prompt)
            targets = [t for p in data['papers'] for t in p['targets']] + data['jointTargets']
            return {'content': json.dumps({'answers': [{'targetId': t['targetId'], 'goalRefs': [], 'point': None}
                                                     for t in targets]}), 'finishReason': 'stop'}
        stage_inputs.prepare = prepare
        try:
            make_synthesize_node(fixture, lambda rid, fn, **kw: repo.update_run(rid, fn, **kw),
                scope_validator=lambda *_: True)({'run_id': r['runId']})
        finally:
            stage_inputs.prepare = native_prepare
        snapshot = repo.require_run(r['runId'])['state']['comparisonStageInput']
        if merged and stage_window == 32000 and profile == original.get('comparisonAuthoringContractVersion'):
            assert [s['prompt'] for s in snapshot['stages']] == [
                s['prompt'] for s in original['state']['comparisonStageInput']['stages']]
        rows = []
        for stage in snapshot['stages']:
            data = packet(stage['prompt'])
            local = [p for p in data['papers'] if p['targets']]
            if (not merged or profile in (2, 3)) and local:
                assert len(data['papers']) == len(local) == 1 and not data['jointTargets']
            rows.append({'id': stage['stageId'], 'inputBytes': stage['inputBytes'],
                'paperCount': len(data['papers']), 'paperTargetCount': sum(len(p['targets']) for p in data['papers']),
                'jointTargetCount': len(data['jointTargets']), 'requiredBundleCount': stage['requiredBundleCount']})
        stage_results.append({'requestedMergeJoint': merged, 'authoringVersion': profile,
            'maxStageInputBytes': snapshot['maxInputBytes'], 'stages': rows,
            'inputBytesTotal': sum(s['inputBytes'] for s in rows),
            'allFrozenPremiseBundlesRetained': snapshot['allFrozenPremiseBundlesRetained'],
            'callLowerBound': snapshot['admission']['callLowerBound'], 'scientificApproval': False})

    rechecks = []
    native_limit = capacity.verification_input_limit
    for limit, profile, override in (() if generation_only else
                                    ((32000, 1, True), (24000, 1, True), (24000, 2, False))):
        repo = DeepResearchRepository(ROOT / 'tmp' / ('comparison-recheck-' + uuid.uuid4().hex + '.sqlite3'))
        repo.initialize()
        record = deepcopy(original)
        record['comparisonAuthoringContractVersion'] = profile
        repo.create_run(record)
        facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
        requests = []
        client = Mock()
        client.invoke.side_effect = AssertionError('Provider invocation forbidden')
        def reserve(**kw):
            requests.append({'node': kw['node'], 'delta': kw['budget_delta'],
                'projectedTokensAtSavedBudget': original['budget']['tokens'] + kw['budget_delta']['tokens'],
                'useReserve': kw['use_reserve'], 'argsDigest': kw['args_digest']})
            # An explicit known-response fixture bypasses the provider; it does
            # not alter the live ledger or pretend to measure provider usage.
            return {'result': {'content': '[]', 'finishReason': 'stop'}}, True
        invoker = TrackedLLMInvoker(client, reserve, lambda *a, **kw: None,
            run_record_fn=repo.require_run, call_history_fn=repo.list_calls,
            verification_max_input_bytes=32000, request_options=research_model_options)
        if override:
            capacity.verification_input_limit = lambda record, node, legacy, configured: (
                min(limit, native_limit(record, node, legacy, configured)) if node == 'verify_repair'
                else native_limit(record, node, legacy, configured))
        try:
            checker = facade._build_semantic_checker(original['runId'], invoker)
            verdicts = checker.check_revisions(original['state']['repairDraft'], original['state']['evidence'], [])
        finally:
            capacity.verification_input_limit = native_limit
            facade.shutdown()
        client.invoke.assert_not_called()
        rechecks.append({'windowBytes': limit, 'authoringVersion': profile, 'prototypeWindowOverride': override,
            'reservationPreviews': requests,
            'unresolvedFixtureVerdictCount': len(verdicts),
            'allRequestsIndividuallyFitSavedTotal': all(r['projectedTokensAtSavedBudget'] <= 100000 for r in requests),
            'sequentialProviderBudgetFitEstablished': False, 'scientificApproval': False})
    assert path.read_bytes() == raw
    shape = lambda result: [{k: s[k] for k in ('id', 'paperCount', 'paperTargetCount', 'jointTargetCount', 'requiredBundleCount')}
                            for s in result['stages']]
    assert shape(stage_results[2]) == shape(stage_results[3])
    assert shape(stage_results[3]) == shape(stage_results[4])
    if not generation_only:
        assert rechecks[1]['reservationPreviews'] == rechecks[2]['reservationPreviews']
    value = {'schemaVersion': 1,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sourceReceiptSha256': hashlib.sha256(raw).hexdigest(),
        'stageAlternatives': stage_results, 'recheckAlternatives': rechecks,
        'providerRequests': 0, 'liveLedgerMutations': 0, 'sourceReceiptUnchanged': True,
        'boundary': 'Actual graph and semantic request construction; null stage and reused empty review fixtures. Stage-only preparation and individual reservations do not establish full-round costs, time or quality.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt-prefix', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--generation-only', action='store_true')
    args = p.parse_args()
    main(args.receipt_prefix, args.output, args.generation_only)
