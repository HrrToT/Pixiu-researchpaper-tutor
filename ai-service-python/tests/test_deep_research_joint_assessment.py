from copy import deepcopy
import json

import pytest

from services.deep_research.joint_assessment import assess,enabled
from services.deep_research.coverage import coverage_gaps
from services.deep_research.contracts import DeepResearchError,UnknownCallError
from services.deep_research.verification import make_evidence,verify_claims


def fixture(works=('a','b')):
    evidence=[];obligations=[]
    for work in works:
        quote=f'We evaluate {work} using our GPU platform and a fixed configuration.'
        ev=make_evidence({'workId':work,'versionId':work+'-v1','contentHash':work+'-hash','accessLevel':'fulltext'},
            quote,quote,location={'page':1},obligation_ids=['old-query-label'])
        evidence.append(ev)
        obligations.append({'obligationId':'ob-'+work,'question':'为什么跨论文结果不能直接比较',
            'requestExcerpt':'为什么跨论文结果不能直接比较','requiredSources':[work],
            'completionCriteria':[{'criterionId':'why','requirement':'解释跨论文比较的条件','responseType':'explanation'}]})
    return {'runId':'r','taskId':'task','question':'解释跨论文比较的条件','jointEvidenceContractVersion':1,
        'evidenceCoverageContractVersion':3,'materials':[{'materialId':w} for w in works],
        'state':{'plan':[{'itemId':'item','question':'比较条件','obligations':obligations,'dependencies':[]}],
                 'evidence':evidence,'sources':[]},'budget':{}}


class Memory:
    def __init__(self,record): self.record=deepcopy(record)
    def update(self,run,mutate,**kwargs):
        self.record=mutate(deepcopy(self.record));return deepcopy(self.record)


def units(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Frozen units (questions, NOT facts):\n',1)[1])[0]


def ready_response(prompt,*,ready=True,refs=None):
    return {'content':json.dumps([{'unitId':u['unitId'],'ready':ready,
        'evidenceIds':(u['evidenceIds'] if refs is None else refs) if ready else []} for u in units(prompt)])}


def execute(memory,invoke,state=None):
    return assess(state or {'run_id':'r'},deepcopy(memory.record),memory.update,invoke,coverage_gaps)


def test_two_partial_source_premises_jointly_close_the_same_frozen_question_without_fact_approval():
    record=fixture();memory=Memory(record);calls=[]
    def invoke(run,node,prompt,options):
        calls.append((node,prompt,options))
        assert len(units(prompt))==1 and len(units(prompt)[0]['members'])==2
        assert all(e['quote'] in prompt for e in record['state']['evidence'])
        return ready_response(prompt)
    result=execute(memory,invoke)
    assert result['stop_reason']=='covered' and not result['gaps'] and len(calls)==1
    assert calls[0][0]=='assess_relevance' and calls[0][2]=={'max_tokens':1536,'temperature':0.0}
    coverage=memory.record['state']['coverage'];assert len(coverage)==2
    for row in coverage:
        assert row['state']=='supported' and row['supportKind']=='joint'
        assert len(row['criteria'][0]['evidenceIds'])==1 and len(row['criteria'][0]['jointEvidenceIds'])==2
    for e in memory.record['state']['evidence']:
        assert e['quote']==next(x['quote'] for x in record['state']['evidence'] if x['evidenceId']==e['evidenceId'])
        assert 'ob-'+e['sourceWorkId'] in e['obligationIds']
        assert not any(oid=='ob-'+w for w in ('a','b') if w!=e['sourceWorkId'] for oid in e['obligationIds'])
    claim={'claimId':'c','kind':'inference','text':'A joint inference.','evidenceRefs':[e['evidenceId'] for e in record['state']['evidence']]}
    assert not verify_claims([claim],record['state']['evidence'])['accepted']
    execute(memory,lambda *_:pytest.fail('No repeated assessment'))
    assert memory.record['state']['assessmentStatus']=='checked'


@pytest.mark.parametrize('bad',['missing_source','foreign_id','duplicate_ref','string_bool','missing_unit','extra_unit','extra_field'])
def test_invalid_or_incomplete_joint_result_cannot_close_any_source(bad):
    memory=Memory(fixture());sent=[]
    def invoke(run,node,prompt,options):
        sent.append(prompt);rows=json.loads(ready_response(prompt)['content'])
        if bad=='missing_source': rows[0]['evidenceIds']=rows[0]['evidenceIds'][:1]
        elif bad=='foreign_id': rows[0]['evidenceIds']=['E99']
        elif bad=='duplicate_ref': rows[0]['evidenceIds']*=2
        elif bad=='string_bool': rows[0]['ready']='true'
        elif bad=='missing_unit': rows=[]
        elif bad=='extra_unit': rows.append({**rows[0],'unitId':'G2'})
        else: rows[0]['verdict']='approved'
        return {'content':json.dumps(rows)}
    result=execute(memory,invoke)
    assert len(result['gaps'])==2 and memory.record['state']['assessmentStatus']=='unchecked'
    assert all(row['state']=='unchecked' for row in memory.record['state']['coverage'])
    execute(memory,lambda *_:pytest.fail('No repeated invalid result'))
    assert len(sent)==1


def test_three_required_sources_are_not_reduced_to_a_two_paper_limit():
    memory=Memory(fixture(('a','b','c')))
    assert not execute(memory,lambda r,n,p,o:ready_response(p))['gaps']
    assert len(memory.record['state']['coverage'])==3
    incomplete=Memory(fixture(('a','b','c')))
    assert len(execute(incomplete,lambda r,n,p,o:ready_response(p,refs=['E1','E2']))['gaps'])==3


def test_single_source_can_combine_multiple_quotes_for_a_mechanism():
    record=fixture(('a',));other=deepcopy(record['state']['evidence'][0]);other['evidenceId']='second-quote'
    other['quote']='The observed error updates the state passed to the next frame.';other['sourceContext']=other['quote']
    record['state']['evidence'].append(other)
    memory=Memory(record)
    assert not execute(memory,lambda r,n,p,o:ready_response(p))['gaps']
    assert len(memory.record['state']['coverage'][0]['criteria'][0]['jointEvidenceIds'])==2


def test_missing_required_version_remains_open_and_requeries_instead_of_accepting_another_version():
    record=fixture();record['state']['plan'][0]['obligations'][1]['requiredSources']=['b-v2']
    memory=Memory(record);result=execute(memory,lambda *_:pytest.fail('Missing version must not dispatch'))
    assert result['gaps'] and result['requery_queries'] and result['stop_reason']==''
    assert any(g['sourceWorkId']=='b-v2' for g in result['gaps'])


def test_full_quote_capacity_failure_does_not_clip_a_required_premise_or_send():
    record=fixture();ev=record['state']['evidence'][0];ev['quote']='x'*26000;ev['sourceContext']=ev['quote']
    memory=Memory(record);result=execute(memory,lambda *_:pytest.fail('No oversized send'))
    assert result['stop_reason']=='assessment_unavailable' and result['gaps']
    assert memory.record['state']['evidence'][0]['quote']==ev['quote']


def test_optional_premises_fit_fewer_rows_without_clipping_or_omitting_a_source():
    record=fixture()
    for i in range(7):
        quote='We report our GPU platform, dataset resolution and original code configuration. '+'z'*5000
        ev=make_evidence({'workId':'a','versionId':'a-v1','contentHash':'large-'+str(i),'accessLevel':'fulltext'},
                        quote,quote,location={'page':i+2},obligation_ids=['old'])
        record['state']['evidence'].append(ev)
    memory=Memory(record);sent=[]
    def invoke(r,n,p,o): sent.append(p);return ready_response(p)
    assert not execute(memory,invoke)['gaps']
    saved=next(iter(next(iter(memory.record['state']['jointAssessment']['scopes'].values())).values()))
    assert 2<=len(saved['evidence'])<6 and len(sent[0].encode('utf8'))<=24000
    assert {e['sourceWorkId'] for e in saved['evidence']}=={'a','b'}
    assert all(e['quote'] in sent[0] for e in saved['evidence'])


def test_untrusted_evidence_or_missing_source_cannot_be_used_as_a_joint_premise():
    record=fixture();record['state']['evidence'][1]['verification']['literal']='unchecked'
    memory=Memory(record);result=execute(memory,lambda *_:pytest.fail('Missing trusted source'))
    assert result['gaps'] and result['requery_queries']
    record=fixture();record['state']['evidence'][1]['sourceWorkId']='outside'
    memory=Memory(record);assert execute(memory,lambda *_:pytest.fail('Foreign source'))['gaps']


@pytest.mark.parametrize('change',['criterion','quote','source_version','new_evidence','round'])
def test_pending_joint_request_cannot_be_bypassed_with_changed_inputs(change):
    memory=Memory(fixture());sent=[]
    def unknown(*args): sent.append(args);raise OSError('Unknown transport')
    with pytest.raises(OSError): execute(memory,unknown)
    state={'run_id':'r'}
    if change=='criterion': memory.record['state']['plan'][0]['obligations'][0]['completionCriteria'][0]['requirement']='A different relationship'
    elif change=='quote': memory.record['state']['evidence'][0]['quote']='Changed original text'
    elif change=='source_version': memory.record['state']['evidence'][0]['sourceVersionId']='a-v2'
    elif change=='new_evidence':
        extra=deepcopy(memory.record['state']['evidence'][0]);extra['evidenceId']='new-id';memory.record['state']['evidence'].append(extra)
    else: state['requery_count']=1
    with pytest.raises(DeepResearchError): execute(memory,lambda *_:pytest.fail('No changed-input resend'),state)
    assert len(sent)==1


def test_new_criterion_does_not_reuse_a_prior_ready_result():
    memory=Memory(fixture());execute(memory,lambda r,n,p,o:ready_response(p))
    memory.record['state']['plan'][0]['obligations'][0]['completionCriteria'][0]['requirement']='Explain a different mechanism'
    result=execute(memory,None)
    assert result['gaps'] and any(g['obligationId']=='ob-a' for g in result['gaps'])


def test_actual_unknown_ledger_request_is_not_reissued(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize();repo.create_run(fixture());repo.begin_execution('r')
    sent=[]
    class Provider:
        def invoke(self,request):
            sent.append(request.prompt);raise LLMProviderError('Unknown',provider='fixture',model='fixture')
    tracked=TrackedLLMInvoker(Provider(),repo.reserve_call,repo.complete_call)
    def invoke(run,node,prompt,options): return tracked(run,node,prompt,options)
    with pytest.raises(LLMProviderError): assess({'run_id':'r'},repo.require_run('r'),repo.update_run,invoke,coverage_gaps)
    with pytest.raises(UnknownCallError): assess({'run_id':'r'},repo.require_run('r'),repo.update_run,invoke,coverage_gaps)
    assert len(sent)==1 and repo.list_calls('r')[0]['status']=='unknown'


def test_settled_result_reuses_exact_request_after_checkpoint_failure(tmp_path):
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize();repo.create_run(fixture());repo.begin_execution('r')
    sent=[]
    class Provider:
        def invoke(self,request):
            sent.append(request.prompt)
            return LLMResult('fixture','fixture',ready_response(request.prompt)['content'],LLMUsage(10,20,30),'stop')
    tracked=TrackedLLMInvoker(Provider(),repo.reserve_call,repo.complete_call)
    def invoke(run,node,prompt,options): return tracked(run,node,prompt,options)
    def update(run,change,**kwargs):
        current=repo.require_run(run);candidate=change(deepcopy(current))
        rounds=[s for scope in candidate.get('state',{}).get('jointAssessment',{}).get('scopes',{}).values() for s in scope.values()]
        if any(s['status']=='received' for s in rounds): raise InterruptedError('After settlement')
        return repo.update_run(run,change,**kwargs)
    with pytest.raises(InterruptedError): assess({'run_id':'r'},repo.require_run('r'),update,invoke,coverage_gaps)
    result=assess({'run_id':'r'},repo.require_run('r'),repo.update_run,invoke,coverage_gaps)
    assert not result['gaps'] and len(sent)==1 and repo.list_calls('r')[0]['status']=='succeeded'


@pytest.mark.parametrize('value',[None,True,False,0,'1',2])
def test_joint_contract_is_strict(value):
    assert not enabled({'jointEvidenceContractVersion':value})
    assert enabled({'jointEvidenceContractVersion':1})


@pytest.mark.parametrize('value',[None,True,0,2])
def test_joint_contract_is_immutable(tmp_path,value):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize();repo.create_run(fixture())
    with pytest.raises(ValueError,match='Immutable run field'):
        repo.update_run('r',lambda r:{**r,'jointEvidenceContractVersion':value})


def test_client_cannot_disable_joint_contract(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'比较条件','materials':[],
                          'jointEvidenceContractVersion':0},start_async=False)
        assert repo.require_run(p['runId'])['jointEvidenceContractVersion']==1
    finally: facade.shutdown()
