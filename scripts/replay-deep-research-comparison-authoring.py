"""Replay recorded comparison responses through real synthesis in isolated SQLite.

Never invokes a provider. Old responses are deliberately not corrected. New input
and display behavior cannot prove that a model follows the changed instructions.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))
from services.deep_research.graph import make_synthesize_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
from services.deep_research.table_bindings import validate_table_bindings
from services.deep_research.comparison_table_context import for_record


def main(prefix, output):
    source_path = Path(str(prefix) + '.payload.json')
    raw = source_path.read_bytes()
    original = json.loads(raw)
    calls = json.loads(Path(str(prefix) + '.calls.json').read_text(encoding='utf-8-sig'))
    model = [c for c in calls if c[3] == 'llm_invoke']
    before = model[:next(i for i, c in enumerate(model) if c[2] == 'synthesize')]
    answers = [a for c in model if c[2] == 'synthesize'
               for a in json.loads(json.loads(c[6])['content'])['answers']]
    if len({a['targetId'] for a in answers}) != len(answers):
        raise ValueError('Duplicate saved target')
    results = []
    for enabled in (False, True):
        record = deepcopy(original)
        record.update(status='running', startedAt=None)
        if enabled:
            record['comparisonAuthoringContractVersion'] = 1
        else:
            record.pop('comparisonAuthoringContractVersion', None)
        record['budget'].update(modelCalls=sum(not c[12] for c in before),
            reservedModelCalls=sum(bool(c[12]) for c in before), elapsedSeconds=0,
            tokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in before),
            normalTokens=sum(json.loads(c[6])['usage']['total_tokens'] for c in before if not c[12]))
        for key in list(record['state']):
            if key.startswith(('repair', 'publication', 'comparison', 'synthesis', 'report', 'verified')) \
                    or key in {'initialVerification', 'initialAnswerCoverage', 'draftValidationAudit',
                               'factualDraftingAudit'}:
                record['state'].pop(key, None)
        db = ROOT / 'tmp' / ('comparison-authoring-replay-' + uuid.uuid4().hex + '.sqlite3')
        repo = DeepResearchRepository(db)
        repo.initialize()
        repo.create_run(record)
        sent = []
        def update(rid, fn, **kw):
            return repo.update_run(rid, fn, **kw)
        def invoke(rid, node, prompt, options, **kw):
            assert node == 'synthesize'
            packet = json.JSONDecoder().raw_decode(prompt.split(
                'Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n', 1)[1])[0]
            data = untables(unpack(packet)) if set(packet) == {'strings', 'value'} else packet
            ids = {t['targetId'] for p in data['papers'] for t in p['targets']}
            ids.update(t['targetId'] for t in data['jointTargets'])
            sent.append(prompt)
            return {'content': json.dumps({'answers': [a for a in answers if a['targetId'] in ids]}, ensure_ascii=False),
                    'finishReason': 'stop'}
        scope = lambda rid, material: material in {m['materialId'] for m in record['materials']}
        outcome = make_synthesize_node(invoke, update, scope_validator=scope)({'run_id': record['runId']})
        saved = repo.require_run(record['runId'])
        state = saved['state']
        snapshot = state['comparisonStageInput']
        if not enabled:
            expected = [s['prompt'] for s in original['state']['comparisonStageInput']['stages']]
            if sent != expected:
                raise AssertionError('Historical inputs changed')
        reopened = DeepResearchRepository(db)
        reopened.initialize()
        again = make_synthesize_node(lambda *a, **kw: (_ for _ in ()).throw(AssertionError('No resend')),
            lambda rid, fn, **kw: reopened.update_run(rid, fn, **kw),
            scope_validator=scope)({'run_id': record['runId']})
        if again['report_version_id'] != outcome['report_version_id']:
            raise AssertionError('Report identity changed on reopen')
        context = for_record(saved)
        checks = []
        for c in state['reportBody']['claims']:
            own = [e for e in state['evidence'] if e['evidenceId'] in c['evidenceRefs']]
            checks.append({'claimId': c['claimId'], 'tableConditionGenerated': '原表测量' in c.get('conditions', {}),
                'tableGate': validate_table_bindings(c, own, translated_metrics=True, dataset_joiners=True,
                    comparison_context=context, bound_duration_spelling=True)})
        results.append({'authoringEnabled': enabled, 'stages': [{'stageId': s['stageId'],
            'inputBytes': s['inputBytes'], 'requiredBundleCount': s['requiredBundleCount'],
            'suppliedEvidenceCount': len(s['suppliedEvidenceIds'])} for s in snapshot['stages']],
            'allFrozenPremiseBundlesRetained': snapshot['allFrozenPremiseBundlesRetained'],
            'claims': checks, 'wireErrors': state['comparisonCellDraft']['answerWireAudit']['errors'],
            'isolatedTargets': [item for entry in state['comparisonStageGeneration']['stages'].values()
                                for item in entry.get('isolatedTargets', [])],
            'sqliteReopenNoResend': True, 'semanticApproval': False})
    if source_path.read_bytes() != raw:
        raise AssertionError('Source receipt changed')
    result = {'schemaVersion': 1,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'receiptSha256': hashlib.sha256(raw).hexdigest(),
        'results': results, 'providerRequests': 0, 'sourceReceiptUnchanged': True,
        'scientificAcceptance': False,
        'boundary': 'Actual synthesis graph and SQLite; saved responses copied unchanged, not generated for new instructions. No semantic approval.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt-prefix', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    main(args.receipt_prefix, args.output)
