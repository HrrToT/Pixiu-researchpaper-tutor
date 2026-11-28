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
import runpy

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ai-service-python'),str(ROOT/'ai-service-python/tests')]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--actual-graph',action='store_true',help='Use actual synthesis-node allocation, not old selected premises')
    args=parser.parse_args()
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
    if args.actual_graph:
        helper=runpy.run_path(str(ROOT/'scripts/replay-deep-research-shared-graph-allocation.py'))
        record,snapshot=helper['capture_input'](original)
        data,aliases=snapshot['data'],snapshot['aliases']
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
    excluded={'resultRoleHintOnly','sourceContextRequired','contextOmitted','obligations'}
    expected_evidence=[{k:v for k,v in row.items() if k not in excluded} for row in data['evidence']]
    assert decoded['evidence']==expected_evidence and decoded['proposal']==p
    assert all(decoded[k]==data[k] for k in data if k!='evidence')
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
    # Exercise the actual repair preparation with a plainly labelled synthetic
    # negative verdict. This grants no scientific credit or production state.
    from services.deep_research.shared_experiment_review import prepare as review_prepare
    from services.deep_research.shared_experiment_revision import prepare as repair_prepare
    from test_deep_research_shared_experiment_review import verdict,reply
    negative=verdict(record,data)
    for row in negative['checks']:
        for binding in row['evidenceBindings']:
            binding['evidenceId']=data['evidence'][0]['evidenceId'];binding['text']=binding['text'][:200]
        for binding in row['planBindings']:binding['text']=binding['text'][:200]
    # Target identifiers are server-owned; select by kind rather than guessing.
    budget_target=next(t['checkId'] for t in review['targets'] if t['kind']=='budgets')
    next(c for c in negative['checks'] if c['checkId']==budget_target).update(
        status='failed',reason='人工容量夹具：预算需要修订，不是科学发现。')
    reviewed_state=review_prepare(record,data,aliases,required_domains=built['requiredDomains'],
        invoke=lambda *a,**k:reply(negative),
        checkpoint=lambda value:record['state'].__setitem__('sharedExperimentReview',deepcopy(value)))
    assert reviewed_state['assessment']['valid'] and not reviewed_state['assessment']['complete'], reviewed_state['assessment'].get('errors')
    repair_saved=[];repair_sends=[]
    def repair_stop(*a,**k):repair_sends.append(a);raise StopBeforeReservation()
    try:
        repair_prepare(record,data,aliases,required_domains=built['requiredDomains'],invoke=repair_stop,
                       checkpoint=lambda value:repair_saved.append(deepcopy(value)))
    except StopBeforeReservation:pass
    repair_input=repair_saved[0]
    result={'scope':'Full review input capacity with all saved public premises and a handwritten interface plan; NOT real generated/scientifically accepted content',
        'inputArtifacts':{k:{'path':str(paths[k].relative_to(ROOT)),'sha256':hashlib.sha256(v).hexdigest()} for k,v in raw.items()},
        'syntheticProposalOnly':True,'syntheticProposalBytes':len(json.dumps(p,ensure_ascii=False,separators=(',',':')).encode()),
        'allocation':'actual_synthesis_node' if args.actual_graph else 'archived17',
        'selectedEvidenceRows':len(decoded['evidence']),
        'scientificEvidenceFieldsAndContextsExact':decoded['evidence']==expected_evidence,
        'excludedServerRoutingMetadata':sorted(excluded),
        'questionRequirementsSourcesTablesExact':all(decoded[k]==data[k] for k in ('question','requirements','sources','tables')),
        'inputBytes':review['inputBytes'],'limitBytes':32000,'headroomBytes':32000-review['inputBytes'],
        'reviewTargets':len(review['targets']),'hardPrecheckIssues':review['hardIssues'],
        'trackedInputAdmissionPassed':admitted,'requestDigestMatchesTrackedInvoker':admitted,
        'estimatedReservation':reservations[0]['budget_delta'] if admitted else None,
        'syntheticNegativeReviewOnly':True,'repairInputBytes':repair_input['inputBytes'],
        'repairPreparationFits':repair_input['inputBytes']<=32000,
        'repairPreparationStatus':repair_input['status'],
        'noRealGeneratedPlanFitClaim':True,'wholeRunTokensAndTimeFitEstablished':False,
        'modelCalls':0,'budgetReservations':0,'applicationWrites':0,'scientificCredit':0,
        'originalArtifactsUnchanged':all(path.read_bytes()==raw[k] for k,path in paths.items())}
    assert result['originalArtifactsUnchanged']
    with output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
