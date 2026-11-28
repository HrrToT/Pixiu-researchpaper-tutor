"""Read saved receipts and diagnose comparison gates without provider dispatch.

The output contains hashes, identities and gate results, never source excerpts or
model prose. Controlled wording only tests deterministic gates, not scientific
approval, generation quality or acceptance of the original failed run.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))

from services.deep_research.table_bindings import validate_table_bindings
from services.deep_research.comparison_table_context import for_record


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def replay(prefix):
    paths = {key: Path(str(prefix) + suffix) for key, suffix in {
        'payload': '.payload.json', 'calls': '.calls.json',
        'execution': '.execution.json', 'restore': '.restore.log'}.items()}
    record, calls, execution, restore = (load(paths[k]) for k in paths)
    state = record['state']
    claims = {row['claimId']: row for row in state['reportBody']['claims']}
    evidence = state['evidence']
    context = for_record(record)
    if context is None:
        raise ValueError('Saved comparison has no valid display context')

    def table(claim):
        own = [e for e in evidence if e['evidenceId'] in claim['evidenceRefs']]
        return validate_table_bindings(claim, own, translated_metrics=True,
            dataset_joiners=True, comparison_context=context, bound_duration_spelling=True)

    # These variants retain exact cited cells and change only display wording.
    # No provider or semantic verifier is invoked, and original claims stay intact.
    original = deepcopy(claims['cmp_5_0'])
    literal_size = deepcopy(original)
    literal_size['text'] = literal_size['text'].replace('存储为', 'Size ')
    explicit_ours = deepcopy(literal_size)
    explicit_ours['text'] = explicit_ours['text'].replace('在Mip-NeRF', '的Ours在Mip-NeRF')
    explicit_ours['text'] = explicit_ours['text'].replace('在Tank', 'Ours在Tank')
    wrong_cell = deepcopy(literal_size)
    wrong_cell['tableBindings'][0]['value'] = '999MB'
    wrong_dataset = deepcopy(literal_size)
    wrong_dataset['text'] = wrong_dataset['text'].replace('Mip-NeRF 360', 'Unrelated dataset')
    wrong_method = deepcopy(literal_size)
    wrong_method['tableBindings'][0]['rowNumber'] = 999
    no_binding = deepcopy(literal_size)
    no_binding['tableBindings'] = []
    original_snapshot = json.dumps(state, sort_keys=True, ensure_ascii=False)
    ablations = {name: table(claim) for name, claim in {
        'original': original, 'literal_size_label': literal_size,
        'explicit_ours_and_size': explicit_ours, 'wrong_cell': wrong_cell,
        'wrong_dataset': wrong_dataset, 'wrong_method': wrong_method,
        'missing_bindings': no_binding}.items()}
    if ablations != {
        'original': 'table_condition_not_displayed', 'literal_size_label': None,
        'explicit_ours_and_size': None, 'wrong_cell': 'table_cell_mismatch',
        'wrong_dataset': 'table_condition_not_displayed',
        'wrong_method': 'unverified_table_cell', 'missing_bindings': 'missing_table_bindings'}:
        raise AssertionError(f'Unexpected table gate results: {ablations}')

    repairs = []
    model_calls = []
    for row in calls:
        # SQLite receipt layout: node, tool, status and settled result payload.
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError('Unexpected saved call format')
        if row[3] != 'llm_invoke':
            continue
        response = json.loads(row[6])
        model_calls.append({'node': row[2], 'status': row[5],
            'model': response.get('model'), 'tokens': response.get('usage', {}).get('total_tokens')})
        if row[2] == 'repair_claims':
            payload = json.loads(response['content'])
            repairs.append({'count': len(payload), 'claimIds': [p['claimId'] for p in payload],
                'unchangedTexts': [p['claimId'] for p in payload
                    if p.get('body', {}).get('prose', {}).get('text') == claims[p['claimId']]['text']]})
    batch = state['repairBatchState']
    terminal = next(row for row in reversed(execution) if row['stage'] == 'terminal_saved')
    final_usage = next(row for row in reversed(execution) if row['stage'] == 'observed')
    if len(model_calls) != final_usage['modelCalls']:
        raise AssertionError('Call receipt count does not match terminal accounting')
    if sum(row['tokens'] for row in model_calls) != final_usage['tokens']:
        raise AssertionError('Settled provider usage does not match terminal accounting')
    claim_results = [{'claimId': cid, 'kind': c['kind'], 'tableGate': table(c),
        'initialReasons': [r['reason'] for r in state['initialVerification']['rejected'] if r['claimId'] == cid],
        'citedEvidenceCount': len(c['evidenceRefs']), 'bindingCount': len(c.get('tableBindings', []))}
        for cid, c in claims.items()]
    if json.dumps(state, sort_keys=True, ensure_ascii=False) != original_snapshot:
        raise AssertionError('Saved state mutated')
    return {
        'schemaVersion': 1, 'runId': record['runId'], 'planningVersion': record['comparisonPlanningContractVersion'],
        'receiptSha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()},
        'terminal': {k: terminal.get(k) for k in ('status', 'outcome', 'errorCode')},
        'usage': {k: final_usage[k] for k in ('modelCalls', 'tokens', 'elapsedSeconds')},
        'modelRequests': model_calls,
        'claims': claim_results,
        'controlledDisplayAblations': ablations,
        'repairResponses': repairs,
        'repairBatches': batch['batches'],
        'compiledRepairIds': {k: [c['claimId'] for c in rows] for k, rows in batch['results'].items()},
        'repairStop': batch.get('stop'), 'restore': restore,
        'stateUnchanged': True, 'providerDispatchesDuringReplay': 0,
        'scientificApproval': False, 'independentAcceptance': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.receipt_prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'claims': len(result['claims']),
        'displayAblations': result['controlledDisplayAblations'], 'newModelCalls': 0}, ensure_ascii=False))
