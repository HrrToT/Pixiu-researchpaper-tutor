from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_stage_inputs import prepare
from services.deep_research.comparison_stage_generation import generate, recorded_response
from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError, digest
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
from test_deep_research_comparison_wire import fixture as wire_fixture
from test_deep_research_comparison_layout import QUESTION
from test_deep_research_comparison_intent import record


def fixture():
    plan,_,_=wire_fixture()
    r=record()
    r.update(runId='stage-r',taskId='stage-t',idempotencyKey='stage-k',status='running',
             startedAt=None,question=QUESTION)
    r['budget'].update(maxModelCalls=18,modelCalls=0,reservedModelCalls=0,
                       maxTokens=100000,tokens=0,normalTokens=0,maxWallClockSeconds=360,elapsedSeconds=0)
    r['state']={'outputKind':'paper_comparison'}
    rows=list(plan['evidence'].values())
    aliases={row['evidenceId']:'original-'+row['evidenceId'] for row in rows}
    bundles=[{'obligationId':o['obligationId'],'criterionId':'c','requirement':o['question'],
              'evidenceIds':[aliases[row['evidenceId']]],'source':row['source']}
             for o in plan['requirements'] for row in rows]
    return r,plan,rows,aliases,bundles


def prepared():
    r,p,rows,aliases,bundles=fixture()
    return r,prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_complete_joint_merge_reduces_calls_without_dropping_targets_or_premise_bundles():
    r,p,rows,aliases,bundles=fixture()
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases)
    assert len(snapshot['stages'])==2
    assert sum(s['requiredBundleCount'] for s in snapshot['stages'])==len(bundles)
    ids=[target for stage in snapshot['stages'] for target in stage['targetIds']]
    assert len(ids)==len(set(ids))==10
    merged=next(s for s in snapshot['stages'] if s['stageId'].endswith('_joint'))
    data=packet(merged)
    assert data['jointTargets'] and sum(bool(p['targets']) for p in data['papers'])==1
    assert all(set(t['evidenceIds'])<=set(merged['suppliedEvidenceIds'])
               for paper in data['papers'] for t in paper['targets'])
    assert snapshot['admission']['callLowerBound']==10


def packet(stage):
    text=stage['prompt'].split('Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n',1)[1]
    data=json.JSONDecoder().raw_decode(text)[0]
    return untables(unpack(data)) if set(data)=={'strings','value'} else data


def null_response(stage):
    return {'content':json.dumps({'answers':[{'targetId':key,'goalRefs':[],'point':None}
                                           for key in stage['targetIds']]}),'finishReason':'stop'}


def test_preparation_keeps_each_bundle_once_source_local_with_typed_tables_and_no_approval():
    r,p,rows,aliases,bundles=fixture();before=deepcopy((r,p,rows,aliases,bundles))
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    assert [s['stageId'] for s in snapshot['stages']]==['P1','P2','joint']
    assert sum(s['requiredBundleCount'] for s in snapshot['stages'])==len(bundles)
    assert snapshot['requirements']==p['requirements'] and not snapshot['scientificApproval']
    for stage in snapshot['stages']:
        data=packet(stage)
        assert data['requirements'] and stage['inputBytes']<=32000
        assert all(e['quote']==p['evidence'][e['evidenceId']]['quote'] for source in data['papers'] for e in source['evidence'])
        assert all(source['tableCatalog'] for source in data['papers'])
        if stage['stageId']!='joint':
            assert len(data['papers'])==1 and data['papers'][0]['source']==stage['stageId'] and not data['jointTargets']
            assert all(set(t['evidenceIds'])<=set(stage['suppliedEvidenceIds']) for t in data['papers'][0]['targets'])
        else:
            assert data['jointTargets'] and not any(source['targets'] for source in data['papers'])
    assert (r,p,rows,aliases,bundles)==before


@pytest.mark.parametrize('mutation',['missing','mixed_owner','unknown_goal','capacity'])
def test_incomplete_evidence_or_mixed_source_bundle_stops_before_generation(mutation):
    r,p,rows,aliases,bundles=fixture()
    if mutation=='missing':bundles[0]['evidenceIds']=['unknown']
    elif mutation=='mixed_owner':bundles[0]['evidenceIds']=list(aliases.values())
    elif mutation=='unknown_goal':bundles[0]['obligationId']='foreign'
    else:rows[0]['quote']='required complete quotation '*10000
    with pytest.raises((DeepResearchError,ValueError)):
        prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_initial_call_floor_and_recovery_use_stable_inputs_not_changed_ledger_counts():
    r,p,rows,aliases,bundles=fixture()
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    assert snapshot['admission']['providerTokensAndWallClockFitEstablished'] is False
    r['budget']['modelCalls']=10
    with pytest.raises(BudgetExhaustedError):prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    r['state']['comparisonStageInput']=snapshot
    assert prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)==snapshot
    rows[0]['quote']+=' changed'
    with pytest.raises(DeepResearchError,match='改变'):
        prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_received_stages_survive_real_sqlite_reopen_without_any_new_dispatch(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    r,snapshot=prepared()
    path=tmp_path/'stages.sqlite3';repo=DeepResearchRepository(path);repo.initialize();repo.create_run(r)
    def current():return repo.require_run(r['runId'])
    def checkpoint(value):
        repo.update_run(r['runId'],lambda run:{**run,'state':{**run['state'],'comparisonStageGeneration':value}})
    sent=[]
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt);sent.append(stage['stageId'])
        assert node=='synthesize' and options['max_tokens']==4000
        return null_response(stage)
    response=generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert sent==['P1','P2','joint'] and len(json.loads(response['content'])['answers'])==10
    repo=DeepResearchRepository(path);repo.initialize();blocked=Mock(side_effect=AssertionError('Unexpected dispatch'))
    assert generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)==response
    blocked.assert_not_called()
    assert not current()['state'].get('verifiedReport')


def test_unknown_stage_never_resends_and_exact_readonly_recovery_can_continue():
    r,snapshot=prepared();sent=[]
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt);sent.append(stage['stageId'])
        if stage['stageId']=='P2':raise TimeoutError('Unknown request')
        return null_response(stage)
    with pytest.raises(TimeoutError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert sent==['P1','P2']
    blocked=Mock(side_effect=AssertionError('Must not resend an uncertain stage'))
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)
    blocked.assert_not_called()
    after=Mock(return_value=null_response(snapshot['stages'][2]))
    response=generate(snapshot,current=current,checkpoint=checkpoint,invoke=after,
                      recover=lambda prompt,options:null_response(snapshot['stages'][1]))
    assert after.call_count==1 and after.call_args.args[1]==snapshot['stages'][2]['prompt']
    assert len(json.loads(response['content'])['answers'])==10


@pytest.mark.parametrize('mutation',['foreign_target','duplicate','truncated','malformed'])
def test_invalid_stage_response_is_durable_and_never_retried(mutation):
    r,snapshot=prepared()
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    response=null_response(snapshot['stages'][0]);body=json.loads(response['content'])
    if mutation=='foreign_target':body['answers'][0]['targetId']=snapshot['stages'][1]['targetIds'][0]
    elif mutation=='duplicate':body['answers'].append(deepcopy(body['answers'][0]))
    elif mutation=='truncated':response['finishReason']='length'
    else:body={'items':[]}
    response['content']=json.dumps(body)
    with pytest.raises(DeepResearchError):
        generate(snapshot,current=current,checkpoint=checkpoint,invoke=Mock(return_value=response))
    blocked=Mock()
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)
    blocked.assert_not_called()
    assert r['state']['comparisonStageGeneration']['stages']['P1']['status']=='invalid_response'


def test_cancel_between_stages_preserves_received_output_without_next_request():
    r,snapshot=prepared();sent=[]
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    def invoke(node,prompt,options):
        sent.append(prompt);r['status']='stopping';return null_response(snapshot['stages'][0])
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert len(sent)==1 and r['state']['comparisonStageGeneration']['stages']['P1']['status']=='compiled_unverified'


@pytest.mark.parametrize('foreign',['evidence','table'])
def test_stage_cannot_borrow_references_from_another_stage(foreign):
    r,snapshot=prepared()
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    raw=[]
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt)
        response=null_response(stage)
        if stage['stageId']=='P1':
            body=json.loads(response['content'])
            body['answers'][0].update(goalRefs=['G1'],point={'kind':'reported',
                'body':{'prose':{'text':'Unverified attempted statement.','conditions':{}}},
                'evidenceRefs':['E2'] if foreign=='evidence' else ['E1'],
                'cellRefs':['foreign-cell'] if foreign=='table' else []})
            response['content']=json.dumps(body);raw.append(deepcopy(response))
        return response
    response=generate(snapshot,current=lambda:deepcopy(r),checkpoint=checkpoint,invoke=invoke)
    assert json.loads(response['content'])['answers'][0]['point'] is None
    entry=r['state']['comparisonStageGeneration']['stages']['P1']
    assert entry['response']==raw[0] and entry['isolatedTargets'][0]['reason']=='stage_'+foreign+'_permission'


@pytest.mark.parametrize('exhausted',['calls','time'])
def test_exhausted_dispatch_budget_does_not_send_the_next_stage(exhausted):
    r,snapshot=prepared()
    if exhausted=='calls':r['budget']['modelCalls']=r['budget']['maxModelCalls']
    else:r['budget']['elapsedSeconds']=r['budget']['maxWallClockSeconds']
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    invoke=Mock()
    with pytest.raises(BudgetExhaustedError):
        generate(snapshot,current=lambda:deepcopy(r),checkpoint=checkpoint,invoke=invoke)
    invoke.assert_not_called()


def test_readonly_ledger_lookup_requires_exact_native_request_identity():
    from services.deep_research.runtime import research_model_options
    from services.deep_research.planning_transport import options_for_record
    from services.deep_research.structured_output import enabled,messages_for_record
    r,snapshot=prepared();r['structuredOutputContractVersion']=15
    prompt=snapshot['stages'][0]['prompt'];options={'max_tokens':4000,'temperature':0.2}
    extra=research_model_options('synthesize',options)
    identity={'prompt':prompt,'extra':extra}
    if enabled(r):
        identity.update(extra=options_for_record(r,'synthesize',extra),messages=messages_for_record(r,'synthesize',prompt))
    row={'runId':r['runId'],'node':'synthesize','tool':'llm_invoke','argsDigest':digest(identity),
         'status':'succeeded','result':null_response(snapshot['stages'][0])}
    before=deepcopy(row)
    assert recorded_response(r,prompt,options,[row])==row['result'] and row==before
    assert recorded_response(r,prompt+'changed',options,[row]) is None
    assert recorded_response(r,prompt,options,[row,row]) is None
    row['status']='unknown'
    assert recorded_response(r,prompt,options,[row]) is None
