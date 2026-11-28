from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest

from services.deep_research.adaptive_assessment import assess
from services.deep_research.coverage import coverage_gaps
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence


def store(tmp_path, *, questions=('Why?',), version=1):
    repo=DeepResearchRepository(str(tmp_path/'r.sqlite3')); repo.initialize()
    plan=[{'itemId':'item','question':'Research','obligations':[
        {'obligationId':f'o{i}','question':q,'requiredSources':['paper']} for i,q in enumerate(questions)]}]
    quote='The method changes a parameter according to the observed signal.'
    e=make_evidence({'workId':'paper','versionId':'v2','contentHash':'h','accessLevel':'fulltext'},
                    quote,quote,location={'page':2},obligation_ids=['o0'])
    repo.create_run({'runId':'r','taskId':'t','adaptiveResearchContractVersion':version,
        'state':{'plan':plan,'evidence':[e],'sources':[{'sourceId':'s','workId':'paper'}]},
        'materials':[{'materialId':'paper'}]})
    repo.begin_execution('r')
    return repo,e


def response(prompt, relevant=True):
    rows=json.JSONDecoder().raw_decode(prompt.split('Pairs:\n',1)[1])[0]
    return {'content':json.dumps([{'pairId':r['pairId'],'relevant':relevant} for r in rows])}


def run(repo,invoke,state=None):
    return assess(state or {'run_id':'r'},repo.require_run('r'),repo.update_run,invoke,coverage_gaps)


def test_confirmed_cross_question_links_are_reused_without_rechecking_or_final_claim_approval(tmp_path):
    repo,e=store(tmp_path,questions=('Why?','How?')); invoke=Mock(side_effect=lambda rid,n,p,o:response(p))
    result=run(repo,invoke)
    assert result['stop_reason']=='covered' and invoke.call_count==1
    saved=repo.require_run('r')['state']
    assert saved['evidence'][0]['obligationIds']==['o0','o1']
    assert saved['evidence'][0]['verification']['semantic']=='unchecked'
    # A replay and a later unchanged round both consume the confirmed verdicts.
    assert run(repo,lambda *_:pytest.fail('No repeat'))['stop_reason']=='covered'
    again=run(repo,lambda *_:pytest.fail('No new review'),{'run_id':'r','requery_count':1,
        'prev_assessment_evidence_digest':result['prev_assessment_evidence_digest']})
    assert again['stop_reason']=='covered'


@pytest.mark.parametrize('malformed', [
    [{'pairId':'R1','relevant':True},{'pairId':'R1','relevant':False}],
    [{'pairId':'other','relevant':True}],[],[{'pairId':'R1','relevant':'true'}],
    [{'pairId':'R1','relevant':True,'status':'passed'}],
])
def test_duplicate_foreign_missing_or_untyped_verdicts_never_close_gaps_or_get_retried(tmp_path,malformed):
    repo,_=store(tmp_path)
    result=run(repo,lambda *_:{'content':json.dumps(malformed)})
    assert result['gaps'] and repo.require_run('r')['state']['assessmentStatus']=='unchecked'
    again=run(repo,lambda *_:pytest.fail('No malformed retry'),{'run_id':'r','requery_count':1,
        'prev_assessment_evidence_digest':result['prev_assessment_evidence_digest']})
    assert again['stop_reason']=='no_new_evidence' and again['gaps']


def test_length_truncation_never_closes_a_gap_even_with_complete_json(tmp_path):
    repo,_=store(tmp_path)
    def invoke(rid,node,prompt,options): return {**response(prompt),'finishReason':'length'}
    assert run(repo,invoke)['gaps']


def test_required_version_is_bound_without_assigning_another_papers_evidence(tmp_path):
    repo,e=store(tmp_path)
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'plan':[{'itemId':'i','question':'Q','obligations':[
        {'obligationId':'version','question':'Explain','requiredSources':['v2']},
        {'obligationId':'foreign','question':'Explain','requiredSources':['other-paper']}]}]}})
    def invoke(rid,node,prompt,options):
        rows=json.JSONDecoder().raw_decode(prompt.split('Pairs:\n',1)[1])[0]
        assert {r['obligationId'] for r in rows}=={'version'}
        return response(prompt)
    result=run(repo,invoke)
    assert {g['obligationId'] for g in result['gaps']}=={'foreign'}
    assert any(c['sourceWorkId']=='v2' and c['state']=='supported' for c in repo.require_run('r')['state']['coverage'])


def test_new_evidence_with_unchanged_source_count_is_progress(tmp_path):
    repo,e=store(tmp_path,questions=('Why?','How?'))
    first=run(repo,lambda rid,n,p,o:response(p,False))
    quote='A new passage describes the additional conditioning input.'
    new=make_evidence({'workId':'paper','versionId':'v2','contentHash':'h','accessLevel':'fulltext'},
                     quote,quote,location={'page':3},obligation_ids=['o0'])
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'evidence':[e,new]}})
    seen=[]
    def invoke(rid,node,prompt,options):
        seen.append(prompt)
        assert new['quote'] in prompt and e['quote'] not in prompt
        rows=json.JSONDecoder().raw_decode(prompt.split('Pairs:\n',1)[1])[0]
        return {'content':json.dumps([{'pairId':r['pairId'],'relevant':r['obligationId']=='o0'} for r in rows])}
    result=run(repo,invoke,{'run_id':'r','requery_count':1,
        'prev_assessment_evidence_digest':first['prev_assessment_evidence_digest']})
    assert len(seen)==1 and result['gaps'] and result['stop_reason']!='no_new_evidence'


def test_normal_budget_denial_records_unchecked_gap_without_provider_call(tmp_path):
    repo,_=store(tmp_path)
    repo.update_run('r',lambda r:{**r,'budget':{**r['budget'],'normalTokens':50000,'tokens':50000}})
    before=deepcopy(repo.require_run('r')['budget'])
    result=run(repo,lambda *_:pytest.fail('No send'))
    assert result['stop_reason']=='assessment_unavailable' and result['gaps']
    assert repo.require_run('r')['budget']==before and repo.list_calls('r')==[]


def test_partial_extraction_budget_flag_still_records_assessment_then_stops_queries(tmp_path):
    from services.deep_research.graph import route_after_extract,route_after_assess
    repo,_=store(tmp_path)
    state={'run_id':'r','budget_exhausted':True,'assess_after_extraction_stop':True}
    assert route_after_extract(state)=='assess'
    result=run(repo,lambda rid,n,p,o:response(p,False),state)
    assert result['gaps'] and result['stop_reason']=='budget_exhausted' and not result['requery_queries']
    assert route_after_assess({**state,**result})=='synthesize'
    assert route_after_extract({'budget_exhausted':True})=='synthesize'  # Legacy behavior.


def test_unknown_propagates_and_real_ledger_blocks_frozen_reissue(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    repo,_=store(tmp_path); provider=Mock()
    provider.invoke.side_effect=LLMProviderError('Unconfirmed',provider='fixture',model='fixture')
    invoke=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    with pytest.raises(LLMProviderError): run(repo,invoke)
    pending=deepcopy(repo.require_run('r')['state']['adaptiveAssessment'])
    assert next(iter(next(iter(pending['scopes'].values())).values()))['status']=='pending'
    with pytest.raises(UnknownCallError): run(repo,invoke)
    assert provider.invoke.call_count==1 and repo.list_calls('r')[0]['status']=='unknown'


def test_settled_verdict_survives_lost_response_checkpoint_with_exact_request(tmp_path):
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.tools import TrackedLLMInvoker
    repo,_=store(tmp_path); provider=Mock()
    provider.invoke.side_effect=lambda req:LLMResult('fixture','fixture',response(req.prompt)['content'],LLMUsage(10,20,30),'stop')
    invoke=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    def update(rid,mutate,**kwargs):
        proposed=mutate(deepcopy(repo.require_run(rid)))
        journal=proposed.get('state',{}).get('adaptiveAssessment',{})
        if any(r.get('status')=='received' for rounds in journal.get('scopes',{}).values() for r in rounds.values()):
            raise InterruptedError('Settlement completed, response checkpoint lost')
        return repo.update_run(rid,lambda _:proposed,**kwargs)
    with pytest.raises(InterruptedError):
        assess({'run_id':'r'},repo.require_run('r'),update,invoke,coverage_gaps)
    assert run(repo,invoke)['stop_reason']=='covered'
    assert provider.invoke.call_count==1 and len(repo.list_calls('r'))==1


def test_empty_extraction_is_reviewed_but_another_page_of_same_source_is_not_skipped(tmp_path):
    from services.deep_research.extraction import make_batched_extract_node
    repo,_=store(tmp_path)
    first='A complete first passage with no requested information for this question.'
    second='The later page contains the conditioning information requested by this question.'
    source={'sourceId':'s','workId':'paper','versionId':'v2','contentHash':'hash','accessLevel':'fulltext',
            'pages':[{'page':1,'text':first}]}
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source],'evidence':[]}})
    sent=[]
    def invoke(rid,node,prompt,options):
        sent.append(prompt)
        return {'content':'[]'}
    extract=make_batched_extract_node(invoke,make_evidence,lambda *_:True,repo.update_run)
    extract({'run_id':'r'}); extract({'run_id':'r'})
    assert len(sent)==1
    source['pages'].append({'page':2,'text':second})
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source]}})
    extract({'run_id':'r'})
    assert len(sent)==2 and second in sent[-1] and first not in sent[-1]
    assert len(repo.require_run('r')['state']['reviewedExtractionPassages'])==2


def test_existing_table_evidence_does_not_skip_unreviewed_prose_in_same_source(tmp_path):
    from services.deep_research.extraction import make_batched_extract_node
    repo,_=store(tmp_path)
    quote='Table row 1: Method | 90'; prose='The method conditions this operation on the observed input before updating its parameters.'
    text=quote+'\n'+prose
    source={'sourceId':'s','workId':'paper','versionId':'v2','contentHash':'hash','accessLevel':'fulltext',
            'pages':[{'page':1,'text':text}]}
    old=make_evidence(source,quote,text,location={'page':1},obligation_ids=['o0']); old['sourceId']='s'
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source],'evidence':[old]}})
    invoke=Mock(return_value={'content':json.dumps([{'sourceId':'s','quote':prose,'obligationIds':['o0'],'conditions':{}}])})
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,repo.update_run)({'run_id':'r'})
    invoke.assert_called_once()
    assert {e['quote'] for e in repo.require_run('r')['state']['evidence']}=={quote,prose}


@pytest.mark.parametrize('changed',[None,True,0,2])
def test_adaptive_contract_cannot_change_after_creation(tmp_path,changed):
    repo,_=store(tmp_path)
    with pytest.raises(ValueError,match='Immutable run field'):
        repo.update_run('r',lambda r:{**r,'adaptiveResearchContractVersion':changed})


def test_compiled_graph_assesses_after_extraction_stop_without_new_acquisition_loop(tmp_path,monkeypatch):
    import services.deep_research.graph as graph_module
    from services.deep_research.contracts import BudgetExhaustedError
    from test_deep_research_end_to_end import FixtureModel,make_facade,create,PAPERS
    def factory(invoke,evidence_fn,validate,update):
        def extract(state):
            evidence=[]
            for work,text in PAPERS.items():
                quote=text.split('. ')[0]+'.'
                ev=make_evidence({'workId':work,'versionId':'v1','contentHash':hashlib.sha256(text.encode()).hexdigest(),
                    'accessLevel':'fulltext'},quote,text,location={'page':3},obligation_ids=['o'])
                ev['sourceId']=f'{work}-chunk-1'; evidence.append(ev)
            update(state['run_id'],lambda r:{**r,'state':{**r['state'],'evidence':evidence}},expected_revision=None)
            raise BudgetExhaustedError('explorationTokens',17000,18000)
        return extract
    monkeypatch.setattr(graph_module,'make_extract_node',factory)
    model=FixtureModel(); repo,facade,retrieved=make_facade(tmp_path,model)
    try:
        record=create(facade); rid=record['runId']; repo.begin_execution(rid); facade._execute_graph(rid)
        final=repo.require_run(rid)
        assert final['status']=='completed',final
        assert final['state']['assessmentStatus']=='checked'
        assert final['state']['stopReason']=='budget_exhausted'
        assert sum(req.prompt.startswith('Assess JOINT EVIDENCE READINESS') for req in model.requests)==1
        assert sum(req.prompt.startswith('For each evidence-obligation pair') for req in model.requests)==0
        assert len(retrieved)==2
        assert '95%' in facade.get(rid)['report']['body']
    finally: facade.shutdown()


def test_client_cannot_disable_adaptive_contract(tmp_path):
    from services.deep_research.facade import ResearchFacade
    repo,_=store(tmp_path); facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'Research',
            'materials':[],'adaptiveResearchContractVersion':0},start_async=False)
        assert repo.require_run(record['runId'])['adaptiveResearchContractVersion']==1
    finally: facade.shutdown()


@pytest.mark.parametrize('truncated',[False,True])
def test_invalid_or_truncated_extraction_is_not_regenerated_in_a_different_batch(tmp_path,truncated):
    from services.deep_research.extraction import make_batched_extract_node
    repo,_=store(tmp_path)
    text='This is the complete source passage used for the requested operation and its conditions.'
    source={'sourceId':'s','workId':'paper','versionId':'v2','contentHash':'hash','accessLevel':'fulltext',
            'pages':[{'page':1,'text':text}]}
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source],'evidence':[]}})
    result={'content':json.dumps([{'sourceId':'s','quote':text,'obligationIds':['o0'],'conditions':{}}]),
            'finishReason':'length'} if truncated else {'content':'not JSON'}
    invoke=Mock(return_value=result)
    node=make_batched_extract_node(invoke,make_evidence,lambda *_:True,repo.update_run)
    node({'run_id':'r'}); node({'run_id':'r'})
    invoke.assert_called_once()
    assert repo.require_run('r')['state']['evidence']==[]


def test_corrupt_extraction_checkpoint_stops_before_dispatch(tmp_path):
    from services.deep_research.extraction import make_batched_extract_node
    from services.deep_research.contracts import DeepResearchError
    repo,_=store(tmp_path)
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'reviewedExtractionPassages':None}})
    with pytest.raises(DeepResearchError,match='片段检查记录'):
        make_batched_extract_node(lambda *_:pytest.fail('No send'),make_evidence,lambda *_:True,repo.update_run)({'run_id':'r'})


def test_corrupt_pending_assessment_stops_before_dispatch(tmp_path):
    from services.deep_research.contracts import DeepResearchError
    repo,_=store(tmp_path)
    def interrupted(*_): raise InterruptedError('Unsent/unknown interruption')
    with pytest.raises(InterruptedError): run(repo,interrupted)
    def corrupt(r):
        for rounds in r['state']['adaptiveAssessment']['scopes'].values():
            for record in rounds.values(): record['request']['prompt']+=' corrupted'
        return r
    repo.update_run('r',corrupt)
    with pytest.raises(DeepResearchError,match='评估请求'):
        run(repo,lambda *_:pytest.fail('No new send'))
