"""Offline repair request/capacity replay through the real verify graph.

Uses the saved pre-repair accounting and original first-two repair charges as a
stress scenario. Empty fixture responses are not provider quality or cost proof.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))
from services.deep_research.graph import make_verify_node
from services.deep_research.verification import verify_claims
from services.deep_research.contracts import BudgetExhaustedError
import services.deep_research.repair as repair


def main(prefix, output):
    path = Path(str(prefix) + '.payload.json')
    raw = path.read_bytes()
    original = json.loads(raw)
    calls = json.loads(Path(str(prefix) + '.calls.json').read_text(encoding='utf-8-sig'))
    models = [c for c in calls if c[3] == 'llm_invoke']
    first = next(i for i, c in enumerate(models) if c[2] == 'repair_claims')
    prior = models[:first]
    charges = [json.loads(c[6])['usage']['total_tokens'] for c in models[first:] if c[2] == 'repair_claims']
    results = []
    native_prepare = repair._prepare_repair
    for enabled in (False, True):
        record = deepcopy(original)
        record.update(status='running', startedAt=None)
        if enabled:
            record['comparisonAuthoringContractVersion'] = 1
        else:
            record.pop('comparisonAuthoringContractVersion', None)
        for key in list(record['state']):
            if key.startswith(('repair', 'publication', 'verified')) and key not in ('repairTargets', 'repairReport'):
                record['state'].pop(key)
        record['budget'].update(modelCalls=sum(not c[12] for c in prior),
            reservedModelCalls=sum(bool(c[12]) for c in prior),
            tokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in prior),
            normalTokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in prior if not c[12]),
            elapsedSeconds=0)
        events = []
        sends = []
        def observe(*args, **kw):
            target_ids = {r['claimId'] for r in args[1]['rejected']}
            event = {'targetIds': [c['claimId'] for c in args[0]['claims'] if c['claimId'] in target_ids],
                     'limit': kw.get('max_prompt_bytes')}
            try:
                prepared = native_prepare(*args, **kw)
                event.update(inputBytes=len(prepared['prompt'].encode('utf-8')), fits=True)
                return prepared
            except BudgetExhaustedError as exc:
                event.update(fits=False, refusal=exc.details)
                raise
            finally:
                events.append(event)
        def update(rid, fn, **kw):
            nonlocal record
            record = fn(deepcopy(record))
            return deepcopy(record)
        def invoke(rid, node, prompt, options, **kw):
            if node != 'repair_claims':
                raise AssertionError('No unexpected provider-capable stage in replay: ' + node)
            index = len(sends)
            sends.append({'inputBytes': len(prompt.encode('utf-8')), 'outputReservation': options.get('_repair_output_limit')})
            if index < len(charges):
                record['budget']['tokens'] += charges[index]
                record['budget']['normalTokens'] += charges[index]
            record['budget']['modelCalls'] += 1
            return {'content': '[]', 'finishReason': 'stop'}
        repair._prepare_repair = observe
        try:
            make_verify_node(verify_claims, None, update, invoke)({'run_id': record['runId']})
        finally:
            repair._prepare_repair = native_prepare
        state = record['state']
        results.append({'authoringEnabled': enabled, 'preparationEvents': events,
            'fixtureRequests': sends, 'repairBatches': state.get('repairBatchState', {}).get('batches'),
            'stop': state.get('repairBatchStop'),
            'outcomeAudit': state.get('repairBatchState', {}).get('comparisonOutcomeAudit'),
            'verifiedClaimCount': len(state.get('verifiedReport', {}).get('verifiedClaims', []))})
    if path.read_bytes() != raw:
        raise AssertionError('Source receipt changed')
    if (len(results[0]['fixtureRequests']) != 2 or len(results[1]['fixtureRequests']) != 3
            or results[1]['stop'] is not None or any(row['verifiedClaimCount'] for row in results)):
        raise AssertionError('Repair stress scenario no longer has the expected bounded outcome')
    result = {'schemaVersion': 1,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sourceReceiptSha256': hashlib.sha256(raw).hexdigest(),
        'providerRequests': 0, 'sourceReceiptUnchanged': True, 'results': results,
        'stressCharges': charges,
        'scientificAcceptance': False, 'providerCostOrTimeFitEstablished': False,
        'boundary': 'Controlled resumption from saved snapshot, not original request identity replay. Original first-two charges are an offline stress scenario; empty responses do not prove model quality, third-request cost, independent recheck or whole-answer capacity.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt-prefix', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    main(a.receipt_prefix, a.output)
