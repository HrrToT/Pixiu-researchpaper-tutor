"""Build the candidate request on saved public evidence; stop before reservation.

Never load application state, invoke a provider or resume any saved attempt.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'ai-service-python'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = (ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT/'docs/deep-research-evidence') or output.exists():
        parser.error('Choose a new file inside docs/deep-research-evidence')
    paths = {
        'run': ROOT/'tmp/dr-acceptance-receipts/D3-VQ-FACTORIAL-v6.payload.json',
        'reviewedRequest': ROOT/'tmp/initialization-readable-483-public-review-20261116/reviewed-request.json',
    }
    raw = {key:path.read_bytes() for key,path in paths.items()}
    original, reviewed = (json.loads(raw[key]) for key in ('run', 'reviewedRequest'))
    from services.deep_research import shared_strings, nested_tables
    from services.deep_research.shared_experiment_generation import MARKER, NODE, INSTRUCTIONS, build, MAX_INPUT
    from services.deep_research.planning_transport import dispatch_options
    from services.deep_research.runtime import research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import digest
    marker = 'Exact authoritative input and unit context (unverified data):\n'
    wire = json.loads(reviewed['request']['prompt'].split(marker,1)[1].split('\n',1)[0])
    context = nested_tables.unpack(shared_strings.unpack(wire))['authoritativeInput']
    # This is the prior model's unverified draft, not a paper premise or a
    # human instruction. The new generation is asked to decide once instead.
    context.pop('unverifiedScientificPlan')
    record = deepcopy(original); record[MARKER] = 1
    original_aliases = original['state']['experimentPlanning']['evidenceAliases']
    aliases = {e['evidenceId']:original_aliases[e['evidenceId']] for e in context['evidence']}
    built = build(record, context, aliases, required_domains=['quality','storage','speed'])
    encoded = json.loads(built['request']['prompt'].split(INSTRUCTIONS,1)[1].split('\n',1)[0])
    decoded = nested_tables.unpack(shared_strings.unpack(encoded)) if set(encoded) == {'strings','value'} else encoded
    assert decoded == context and built['inputBytes'] <= MAX_INPUT
    reservations = []
    class BeforeReservation(Exception): pass
    def reserve(**kwargs):
        reservations.append(kwargs)
        raise BeforeReservation()
    def complete(*args, **kwargs): raise AssertionError('No request may complete')
    invoke = TrackedLLMInvoker(object(), reserve, complete, request_options=research_model_options,
        run_record_fn=lambda rid:deepcopy(record), experiment_max_input_bytes=32000)
    try:
        request = built['request']
        invoke(record['runId'], NODE, request['prompt'], dispatch_options(record,NODE,request['extra']),use_reserve=True)
        raise AssertionError('Expected interception before reservation')
    except BeforeReservation:
        pass
    assert len(reservations) == 1 and reservations[0]['args_digest'] == digest(built['request'])
    proof = {
        'scope':'Closed counterfactual candidate request on saved D3 public evidence; interrupted before budget reservation, never a model run or resume',
        'inputArtifacts':{k:{'path':str(paths[k].relative_to(ROOT)), 'sha256':hashlib.sha256(v).hexdigest()} for k,v in raw.items()},
        'frozenHistoricalRecordUnchanged':True, 'candidatePolicyAppliedOnlyToLocalCopy':True,
        'all17RequiredEvidenceRowsAndContextsExact':len(decoded['evidence']) == 17 and decoded['evidence'] == context['evidence'],
        'questionExact':decoded['question'] == original['question'],
        'requirementsSourcesAndTablesExact':all(decoded[k] == context[k] for k in ('requirements','sources','tables')),
        'inputBytes':built['inputBytes'], 'promptBytes':built['promptBytes'],
        'transportOverheadBytes':built['transportOverheadBytes'], 'limitBytes':MAX_INPUT,
        'headroomBytes':MAX_INPUT-built['inputBytes'],
        'requestDigestMatchesActualTrackedInvoker':True,
        'estimatedAtomicReservation':reservations[0]['budget_delta'],
        'reservationBoundary':'Estimate only, no reservation was committed and no actual usage was measured.',
        'systemPolicyBytes':len(built['request']['messages'][0]['content'].encode('utf-8')),
        'outputTokens':built['request']['extra']['max_tokens'],
        'wholeRunTokensAndTimeFitEstablished':False,
        'modelCalls':0,'applicationWrites':0,'budgetReservations':0,'runtimeLoaded':False,'scientificCredit':0,
        'originalArtifactsUnchanged':all(path.read_bytes() == raw[k] for k,path in paths.items()),
    }
    assert proof['originalArtifactsUnchanged']
    with output.open('x',encoding='utf-8') as out:
        json.dump(proof,out,ensure_ascii=False,indent=2); out.write('\n')
    print(json.dumps(proof,ensure_ascii=False))


if __name__ == '__main__': main()
