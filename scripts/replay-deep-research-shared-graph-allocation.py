"""Replay saved D3 through the real synthesis node, stopping before preparation.

No historical run is resumed, no budget is reset/reserved, and no model is used.
"""
from copy import deepcopy
import argparse,hashlib,json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ai-service-python'))


def capture_input(original):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.shared_experiment_generation import MARKER,build
    from services.deep_research.selection import surrounding_context
    current=deepcopy(original);current[MARKER]=1;captures=[];sends=[]
    class StopBeforePreparation(Exception):pass
    def update(rid,fn,**kwargs):
        nonlocal current
        value=fn(deepcopy(current))
        if 'sharedExperimentInput' in value['state']:
            captures.append(deepcopy(value['state']['sharedExperimentInput']));raise StopBeforePreparation()
        current=value;return deepcopy(current)
    def invoke(*args,**kwargs):sends.append(args[1]);raise AssertionError('No model invocation permitted')
    try:
        make_synthesize_node(invoke,update)({'run_id':current['runId']})
        raise AssertionError('Expected interception before generation preparation')
    except StopBeforePreparation:pass
    assert len(captures)==1 and not sends
    return current,captures[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT/'docs/deep-research-evidence') or output.exists():parser.error('Choose a fresh evidence file')
    path=ROOT/'tmp/dr-acceptance-receipts/D3-VQ-FACTORIAL-v6.payload.json';raw=path.read_bytes();original=json.loads(raw)
    from services.deep_research.shared_experiment_generation import build
    from services.deep_research.selection import surrounding_context
    current,snapshot=capture_input(original)
    built=build(current,snapshot['data'],snapshot['aliases'],required_domains=snapshot['requiredDomains'])
    old_aliases=original['state']['experimentPlanning']['evidenceAliases']
    required_aliases=original['state']['executionWorkflowBlueprint']['units']['baseline']['premiseAllocation']['requiredAliases']
    required_ids={old_aliases[e] for e in required_aliases};selected=set(snapshot['aliases'].values())
    stored={e['evidenceId']:e for e in original['state']['evidence']}
    exact=all(row['quote']==stored[snapshot['aliases'][row['evidenceId']]]['quote']
              and row['sourceContext']==surrounding_context(stored[snapshot['aliases'][row['evidenceId']]])
              for row in snapshot['data']['evidence'])
    assert required_ids<=selected and exact and built['inputBytes']<=32000 and path.read_bytes()==raw
    result={'scope':'Actual synthesis-node allocation replay only; stopped before preparing/reserving/sending any request',
        'archivedRunSha256':hashlib.sha256(raw).hexdigest(),'candidatePolicyOnlyInLocalCopy':True,
        'old17RequiredPremisesRetained':len(required_ids)==17 and required_ids<=selected,
        'selectedEvidenceRows':len(selected),'allSelectedQuotesAndContextsExact':exact,
        'selectedActualEvidenceIds':sorted(selected),'requiredActualEvidenceIds':sorted(required_ids),
        'originalEvidenceRowsRemainInRun':len(original['state']['evidence']),
        'generationInputBytes':built['inputBytes'],'inputLimitBytes':32000,'headroomBytes':32000-built['inputBytes'],
        'nativeRequestDigest':__import__('services.deep_research.contracts',fromlist=['digest']).digest(built['request']),
        'originalArtifactsUnchanged':True,'modelCalls':0,'budgetReservations':0,'applicationWrites':0,'scientificCredit':0,
        'wholeRunFitEstablished':False,'next':'Frozen full regression, then real funded D3 validation with one unique receipt; no scientific credit from allocation replay.'}
    with output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in result.items() if 'EvidenceIds' not in k},ensure_ascii=False))


if __name__=='__main__':main()
