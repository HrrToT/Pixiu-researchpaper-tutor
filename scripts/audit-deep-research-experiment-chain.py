"""Read-only capacity audit of the archived D3 chain; never invoke a provider.

This audit distinguishes a best-case call floor from a feasible complete run.
It does not synthesize missing initializers or amend saved run policies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-service-python'))


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / 'docs/deep-research-evidence'):
        parser.error('Output must be inside docs/deep-research-evidence')
    if output.exists():
        parser.error('Evidence exists; do not overwrite')
    paths = {
        'run': ROOT / 'tmp/dr-acceptance-receipts/D3-VQ-FACTORIAL-v6.payload.json',
        'calls': ROOT / 'tmp/dr-acceptance-receipts/D3-VQ-FACTORIAL-v6.calls.json',
        'reviewedRequest': ROOT / 'tmp/initialization-readable-483-public-review-20261116/reviewed-request.json',
        'workflowImplementation': ROOT / 'ai-service-python/services/deep_research/workflow_units.py',
    }
    raw = {key: path.read_bytes() for key, path in paths.items()}
    run, calls, reviewed = (json.loads(raw[key]) for key in ('run', 'calls', 'reviewedRequest'))
    blueprint = run['state']['executionWorkflowBlueprint']
    meta = blueprint['units']['metadata']['value']
    model_calls = [call for call in calls if call['tool'] == 'llm_invoke']
    assert all(call['settled'] == 1 for call in model_calls)
    budget = run['budget']
    spent = budget['modelCalls'] + budget['reservedModelCalls']
    assert spent == len(model_calls)
    remaining = budget['maxModelCalls'] - spent
    initialization = int(meta['baselineMode'] == 'train') + len(meta['components'])
    # These are optimistic floors, not a forecast: source checks and multiple
    # review/audit requests may cost more, and a repair may fail or need reviews.
    after_workflow = {'publicGeneration': 1, 'scientificReviewFloor': 1, 'wholeAnswerAuditFloor': 1}
    floor = initialization + sum(after_workflow.values())
    repair_floor = 2  # one edit and at least one subsequent review/audit
    request = reviewed['request']
    marker = 'Exact authoritative input and unit context (unverified data):\n'
    wire = json.loads(request['prompt'].split(marker, 1)[1].split('\n', 1)[0])
    from services.deep_research import shared_strings, nested_tables
    view = nested_tables.unpack(shared_strings.unpack(wire))
    assert set(view) == {'authoritativeInput', 'unitContext'}
    from services.deep_research.planning_transport import overhead_bytes
    transport_bytes = overhead_bytes(reviewed['record'], 'plan_workflow_init', request['extra'])
    input_bytes = len(request['prompt'].encode('utf-8')) + transport_bytes
    proof = {
        'scope': 'Archived D3 call floor and reviewed initializer input decomposition; no generation or feasibility certification',
        'inputArtifacts': {key: {'path': str(paths[key].relative_to(ROOT)), 'sha256': hashlib.sha256(value).hexdigest()}
                           for key, value in raw.items()},
        'runId': run['runId'], 'archivedError': run['errorCode'],
        'metadata': {'components': len(meta['components']), 'phases': len(meta['phases']), 'baselineMode': meta['baselineMode']},
        'callFloor': {'maximum': budget['maxModelCalls'], 'spentIncludingReservePool': spent,
                      'remaining': remaining, 'remainingInitializerRequests': initialization,
                      'afterWorkflow': after_workflow, 'minimumAdditionalCalls': floor,
                      'optimisticSpareCalls': remaining - floor,
                      'repairAndRecheckFloor': repair_floor,
                      'fitsFloorWithOneRepairAndRecheck': remaining >= floor + repair_floor,
                      'sharedRepresentationExtraCallIncluded': False,
                      'tokensAndTimeFitEstablished': False},
        'reviewedInitializerInput': {
            'promptBytes': len(request['prompt'].encode('utf-8')), 'transportOverheadBytes': transport_bytes,
            'inputBytes': input_bytes, 'limitBytes': 32000, 'headroomBytes': 32000-input_bytes,
            'maxOutputTokens': request['extra']['max_tokens'],
            'decodedInputFieldBytes': {k: len(packed(v).encode('utf-8')) for k, v in view.items()},
            'decodedAuthoritativeFieldBytes': {k: len(packed(v).encode('utf-8')) for k, v in view['authoritativeInput'].items()},
            'measurementBoundary': 'Decoded field sizes do not add to packed wire size; no content was dropped or rewritten.'},
        'findings': [
            'The best-case call floor fits, but does not leave the two-call repair-and-recheck floor.',
            'The reviewed baseline input fits with little headroom; later component inputs and output completion remain unproved.',
            'A missing initializer cannot be fabricated for downstream capacity simulation.',
            'A complete experiment must preserve intervention, initial state provenance, update schedule, budget, measurement and paired effects.'
        ],
        'modelCalls': 0, 'applicationWrites': 0, 'scientificCredit': 0,
        'originalArtifactsUnchanged': all(path.read_bytes() == raw[key] for key, path in paths.items()),
    }
    assert proof['originalArtifactsUnchanged']
    with output.open('x', encoding='utf-8') as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(packed(proof))


if __name__ == '__main__':
    main()
