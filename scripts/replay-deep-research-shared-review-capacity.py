"""Measure full scientific-review input with archived evidence and a synthetic plan.

The proposal is a handwritten test fixture, NOT a saved/new model answer. Stop
before reservation; no provider, production write, run resume or quality credit.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ai-service-python'),str(ROOT/'ai-service-python/tests')]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT/'docs/deep-research-evidence') or output.exists():
        parser.error('Choose a new evidence file')
    paths={'run':ROOT/'tmp/dr-acceptance-receipts/D3-VQ-FACTORIAL-v6.payload.json',
           'input':ROOT/'tmp/initialization-readable-483-public-review-20261116/reviewed-request.json',
           'fixture':ROOT/'ai-service-python/tests/test_deep_research_shared_experiment_plan.py'}
    raw={k:p.read_bytes() for k,p in paths.items()}
    original=json.loads(raw['run']);reviewed=json.loads(raw['input'])
    from services.deep_research import shared_strings,nested_tables
    from services.deep_research.shared_experiment_generation import build as generation_input,MARKER
    from services.deep_research.shared_experiment_plan import bind_for_review
    from services.deep_research.shared_experiment_review import build,NODE,INSTRUCTIONS
    from services.deep_research.contracts import digest
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from services.deep_research.planning_transport import dispatch_options
    from test_deep_research_shared_experiment_plan import proposal
    marker='Exact authoritative input and unit context (unverified data):\n'
    wire=json.loads(reviewed['request']['prompt'].split(marker,1)[1].split('\n',1)[0])
    data=nested_tables.unpack(shared_strings.unpack(wire))['authoritativeInput'];data.pop('unverifiedScientificPlan')
    record=deepcopy(original);record[MARKER]=1
    aliases={e['evidenceId']:original['state']['experimentPlanning']['evidenceAliases'][e['evidenceId']] for e in data['evidence']}
    built=generation_input(record,data,aliases,required_domains=['quality','storage','speed'])
    p=proposal();quote=data['evidence'][0]['quote'];assert len(quote)<=1600
    p['sourceFacts']=[{'id':'F1','text':quote,'evidenceRefs':[data['evidence'][0]['evidenceId']]}]
    bound=bind_for_review(p,built['allowedEvidenceIds'],context_digest=built['contextDigest'],required_domains=built['requiredDomains'])
    response={'content':json.dumps(p,ensure_ascii=False),'finishReason':'stop'}
    record['state']['sharedExperimentGeneration']={**built,'version':1,'status':'awaiting_scientific_review',
        'boundProposal':bound,'bindingDigest':bound['bindingDigest'],'response':response,'responseDigest':digest(response)}
    review=build(record,data,aliases,required_domains=built['requiredDomains'])
    encoded=json.loads(review['request']['prompt'].split(INSTRUCTIONS,1)[1].split('\n',1)[0])
    decoded=nested_tables.unpack(shared_strings.unpack(encoded)) if set(encoded)=={'strings','value'} else encoded
    assert all(decoded[k]==data[k] for k in data) and decoded['proposal']==p
    reservations=[]
    class StopBeforeReservation(Exception):pass
    def reserve(**kwargs):reservations.append(kwargs);raise StopBeforeReservation()
    invoke=TrackedLLMInvoker(object(),reserve,lambda *args,**kwargs:None,request_options=research_model_options,
                            run_record_fn=lambda rid:deepcopy(record),experiment_max_input_bytes=32000)
    admitted=False
    try:
        req=review['request'];invoke(record['runId'],NODE,req['prompt'],dispatch_options(record,NODE,req['extra']),use_reserve=True)
    except StopBeforeReservation: admitted=True
    except ValueError: pass
    if admitted: assert len(reservations)==1 and reservations[0]['args_digest']==digest(review['request'])
    result={'scope':'Full review input capacity with all saved public premises and a handwritten interface plan; NOT real generated/scientifically accepted content',
        'inputArtifacts':{k:{'path':str(paths[k].relative_to(ROOT)),'sha256':hashlib.sha256(v).hexdigest()} for k,v in raw.items()},
        'syntheticProposalOnly':True,'syntheticProposalBytes':len(json.dumps(p,ensure_ascii=False,separators=(',',':')).encode()),
        'all17OriginalEvidenceRowsAndContextsExact':len(decoded['evidence'])==17 and decoded['evidence']==data['evidence'],
        'questionRequirementsSourcesTablesExact':all(decoded[k]==data[k] for k in ('question','requirements','sources','tables')),
        'inputBytes':review['inputBytes'],'limitBytes':32000,'headroomBytes':32000-review['inputBytes'],
        'reviewTargets':len(review['targets']),'hardPrecheckIssues':review['hardIssues'],
        'trackedInputAdmissionPassed':admitted,'requestDigestMatchesTrackedInvoker':admitted,
        'estimatedReservation':reservations[0]['budget_delta'] if admitted else None,
        'noRealGeneratedPlanFitClaim':True,'wholeRunTokensAndTimeFitEstablished':False,
        'modelCalls':0,'budgetReservations':0,'applicationWrites':0,'scientificCredit':0,
        'originalArtifactsUnchanged':all(path.read_bytes()==raw[k] for k,path in paths.items())}
    assert result['originalArtifactsUnchanged']
    with output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
