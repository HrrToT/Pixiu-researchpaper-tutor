from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError,UnknownCallError
from services.deep_research.shared_experiment_answer import prepare as answer,slot as answer_slot,validated_saved
from services.deep_research.shared_experiment_revision import prepare as repair,apply,view,NODE as REPAIR
from services.deep_research.shared_experiment_review import prepare as science,review_slot,NODE as SCIENCE
from services.deep_research.shared_experiment_pipeline import verify
from test_deep_research_shared_experiment_review import ready,check,verdict,reply


def coverage(prompt,missing=False):
    from services.deep_research import shared_strings,nested_tables
    marker='Exact decision input fields (question, fixed checks, complete accepted claims and server metadata):\n'
    wire=json.JSONDecoder().raw_decode(prompt.rsplit(marker,1)[1])[0]
    data=nested_tables.unpack(shared_strings.unpack(wire)) if set(wire)=={'strings','value'} else wire
    rows=[]
    cid='shared_experiment_answer'
    for goal in data['requirements']:
        checks=[]
        for required in goal['checks']:
            row={'checkId':required['checkId'],'status':'missing' if missing else 'covered',
                 'bindings':[] if missing else [{'claimId':cid,'field':'text'}],
                 'reason':'离线接口夹具，不是科学内容验收。'}
            if required.get('responseType')=='limitation':row['limitSpans']=[]
            if required.get('processRequired'):row['processLinks']=[]
            checks.append(row)
        rows.append({'obligationId':goal['obligationId'],'checks':checks})
    rows.append({'auditType':'answer_coherence','coherent':True,'issues':[]})
    return {'content':json.dumps(rows,ensure_ascii=False)}


def updater(record):
    def update(rid,fn,**kwargs):
        value=fn(deepcopy(record));record.clear();record.update(deepcopy(value));return deepcopy(record)
    return update


def test_existing_fixed_request_final_audit_is_bound_cached_and_revalidated():
    r,data,aliases=ready();check(r,data,aliases)
    sent=Mock(side_effect=lambda rid,node,prompt,opts,**kw:coverage(prompt))
    def save(v):r['state'][answer_slot(r)]=deepcopy(v)
    result=answer(r,data,aliases,invoke=sent,checkpoint=save)
    assert result['complete'],result['audit']
    assert answer(r,data,aliases,invoke=sent,checkpoint=save)==result and sent.call_count==1
    r['state'][answer_slot(r)]['audit']['gaps']=[{'invented':'gap'}]
    with pytest.raises(DeepResearchError):validated_saved(r,data,aliases)


def test_final_audit_budget_stop_retains_candidate_without_sending_or_repair():
    r,data,aliases=ready();check(r,data,aliases)
    r['budget'].update(modelCalls=18,reservedModelCalls=0)
    sent=Mock(side_effect=AssertionError('Exhausted budget must stop before model invocation'))
    def save(value):r['state'][answer_slot(r)]=deepcopy(value)
    result=answer(r,data,aliases,invoke=sent,checkpoint=save)
    assert not result['complete'] and not result['repairEligible']
    assert result['candidate']['markdown'] and r['state'][answer_slot(r)]['calls']=={}
    assert validated_saved(r,data,aliases)==result
    sent.assert_not_called()


def diagnosed():
    r,data,aliases=ready();v=verdict(r,data)
    v['checks'][6].update(status='failed',reason='需要修正实验预算。')
    check(r,data,aliases,v)
    return r,data,aliases


def edit_response(r):
    return reply({'baseDigest':r['state']['sharedExperimentGeneration']['bindingDigest'],
                  'edits':[{'path':'/budgets/1/cap','value':20}],'unresolved':[]})


def test_one_explicit_repair_preserves_base_and_needs_new_science_review():
    r,data,aliases=diagnosed();base=deepcopy(r['state']['sharedExperimentGeneration']);old=deepcopy(r['state']['sharedExperimentReview'])
    sent=Mock(return_value=edit_response(r))
    def save(v):r['state']['sharedExperimentRevision']=deepcopy(v)
    result=repair(r,data,aliases,invoke=sent,checkpoint=save)
    assert result['status']=='awaiting_scientific_review' and sent.call_count==1
    assert r['state']['sharedExperimentGeneration']==base and r['state']['sharedExperimentReview']==old
    assert view(r)['boundProposal']['proposal']['budgets'][1]['cap']==20
    assert view(r)['origin']=='revision' and view(r)['sourceGenerationBindingDigest']==base['bindingDigest']
    from services.deep_research.shared_experiment_result import compile_candidate
    with pytest.raises(DeepResearchError):compile_candidate(r,data,aliases)
    assert repair(r,data,aliases,invoke=sent,checkpoint=save)==result and sent.call_count==1
    science(r,data,aliases,invoke=Mock(return_value=reply(verdict(r,data))),
            checkpoint=lambda v:r['state'].__setitem__(review_slot(r),deepcopy(v)))
    assert '20 优化步' in compile_candidate(r,data,aliases)['markdown']
    assert '10 优化步' in base['boundProposal']['proposal']['budgets'][1]['stopRule'] or base['boundProposal']['proposal']['budgets'][1]['cap']==10


@pytest.mark.parametrize('mutation',['base','overlap','unknown','version','invalid_value','no_change','duplicate'])
def test_replacements_cannot_change_authority_or_silently_fill_science(mutation):
    r,_,_=diagnosed();base=r['state']['sharedExperimentGeneration']; response=edit_response(r);v=json.loads(response['content'])
    if mutation=='base':v['baseDigest']='0'*64
    elif mutation=='overlap':v['edits'].append({'path':'/budgets','value':base['boundProposal']['proposal']['budgets']})
    elif mutation=='unknown':v['edits'][0]['path']='/not_a_field'
    elif mutation=='version':v['edits'][0]={'path':'/version','value':1}
    elif mutation=='invalid_value':v['edits'][0]['value']=-1
    elif mutation=='no_change':v['edits'][0]['value']=10
    else:v['edits'].append(deepcopy(v['edits'][0]))
    with pytest.raises((ValueError,KeyError)):apply(base,reply(v))


def test_invalid_review_response_and_unknown_are_not_repair_eligibility():
    r,data,aliases=ready()
    def save(v):r['state']['sharedExperimentReview']=deepcopy(v)
    science(r,data,aliases,invoke=Mock(return_value=reply({})),checkpoint=save)
    sent=Mock()
    with pytest.raises(DeepResearchError):repair(r,data,aliases,invoke=sent,checkpoint=lambda v:None)
    sent.assert_not_called()


@pytest.mark.parametrize('fixed',[True,False])
def test_graph_verifier_repairs_at_most_once_and_rechecks_both_stages(fixed):
    r,data,aliases=ready();r['state']['sharedExperimentInput']={'data':data,'aliases':aliases,'requiredDomains':[]}
    update=updater(r);calls=[];review_count=[0]
    def invoke(rid,node,prompt,opts,**kw):
        calls.append(node)
        if node==SCIENCE:
            review_count[0]+=1;v=verdict(r,data)
            if review_count[0]==1 or not fixed:v['checks'][6].update(status='failed',reason='需要修正预算。')
            return reply(v)
        if node==REPAIR:return edit_response(r)
        assert node=='verify_answer_coverage';return coverage(prompt)
    result=verify(r,update,invoke)
    assert calls.count(REPAIR)==1 and calls.count(SCIENCE)==2
    assert r['state']['sharedExperimentRelease']['complete'] is fixed
    before=list(calls);assert verify(r,update,invoke)==result and calls==before
    assert 'sharedExperimentRevisionReview' in r['state']


@pytest.mark.parametrize('tracked_http',[False,True])
def test_actual_synthesis_verify_publish_nodes_and_scope_gate(tmp_path,monkeypatch,tracked_http):
    _exercise_graph(tmp_path,monkeypatch,tracked_http)


@pytest.mark.parametrize('scenario',['final_gap_repair','settled_review_checkpoint_crash'])
def test_tracked_graph_repair_and_checkpoint_recovery(tmp_path,monkeypatch,scenario):
    _exercise_graph(tmp_path,monkeypatch,True,scenario)


def _exercise_graph(tmp_path,monkeypatch,tracked_http,scenario=None):
    from services.deep_research.graph import make_synthesize_node,make_verify_node,make_publish_node
    from services.deep_research.shared_experiment_generation import NODE as GENERATE
    from test_deep_research_shared_experiment_generation import context,response
    from services.deep_research.repository import DeepResearchRepository
    r,data,aliases=context()
    if tracked_http:
        r['budget'].update(reserveModelCalls=5,reserveTokens=50000,finalizationBudgetVersion=1,
                           releasedReserveTokens=0,tokens=0,normalTokens=0,elapsedSeconds=0)
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run(r);repo.begin_execution('r')
    crash=[scenario=='settled_review_checkpoint_crash']
    def update(rid,fn,**kw):
        if crash[0]:
            proposed=fn(deepcopy(repo.require_run(rid)))
            if proposed['state'].get('sharedExperimentReview',{}).get('status')=='response_received':
                crash[0]=False
                raise RuntimeError('fixture: response settled before checkpoint')
        return repo.update_run(rid,fn,**kw)
    calls=[]
    def fixture_invoke(rid,node,prompt,opts,**kw):
        calls.append(node);current=repo.require_run(rid)
        if node==GENERATE:return response()
        if node==SCIENCE:return reply(verdict(current,data))
        if node==REPAIR:return edit_response(current)
        assert node=='verify_answer_coverage'
        return coverage(prompt,missing=scenario=='final_gap_repair' and calls.count(node)==1)
    invoke=fixture_invoke
    if tracked_http:
        from services.deep_research.tools import TrackedLLMInvoker
        from services.deep_research.runtime import ScopedModelClient,research_model_options
        from llm.client import DeepSeekLLM
        from test_deep_research_schema_transport import response as http_response
        active=[]
        def post(*args,**kwargs):
            rid,node,prompt,opts=active[-1]
            content=fixture_invoke(rid,node,prompt,opts)['content']
            if args[0].endswith('/responses'):return http_response(content)
            http=Mock(status_code=200)
            http.json.return_value={'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':11,'completion_tokens':5,'total_tokens':16}}
            return http
        monkeypatch.setattr('llm.client.requests.post',post)
        provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
        client=ScopedModelClient(repo,lambda *args:True,lambda:provider).for_run('r')
        tracked=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,
            request_options=research_model_options,run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
        def invoke(rid,node,prompt,opts,**kwargs):
            active.append((rid,node,prompt,opts))
            return tracked(rid,node,prompt,opts,**kwargs)
    state={'run_id':'r','execution_epoch':repo.require_run('r')['executionEpoch']}
    state.update(make_synthesize_node(invoke,update)(state))
    assert not state.get('error_code'),state
    verifier=make_verify_node(Mock(),None,update,llm_invoke=invoke)
    if scenario=='settled_review_checkpoint_crash':
        with pytest.raises(RuntimeError,match='response settled'):verifier(state)
        assert len(repo.list_calls('r'))==2 and all(c['settled']==1 for c in repo.list_calls('r'))
        assert repo.require_run('r')['state']['sharedExperimentReview']['status']=='pending'
    state.update(verifier(state))
    expected=[GENERATE,SCIENCE,'verify_answer_coverage']
    if scenario=='final_gap_repair':expected.extend([REPAIR,SCIENCE,'verify_answer_coverage'])
    assert calls==expected
    before=list(calls);assert verifier(state)['report_version_id']==state['report_version_id'] and calls==before
    with pytest.raises(DeepResearchError) as error:make_publish_node(repo.publish_report,update,scope_validator=lambda *args:False)(state)
    assert error.value.code=='scope_revoked' and not repo.require_run('r')['publication'].get('publicationId')
    assert not repo.pending_publications()
    result=make_publish_node(repo.publish_report,update,scope_validator=lambda *args:True)(state)
    assert result['outcome']=='complete'
    published=repo.require_run('r');assert published['status']=='completed' and published['state']['reportText']
    assert published['state']['sharedExperimentRelease']['complete'] is True
    before=list(calls);make_publish_node(repo.publish_report,update,scope_validator=lambda *args:True)(state)
    assert calls==before
    if tracked_http:
        ledger=repo.list_calls('r')
        assert len(ledger)==len(expected) and all(c['settled']==1 and c['status']=='succeeded' for c in ledger)
        assert repo.require_run('r')['budget']['tokens']==16*len(expected)
        if scenario=='final_gap_repair':
            assert sum(c['usesReserve'] for c in ledger)==5
            assert repo.require_run('r')['budget']['reservedModelCalls']==5
            assert repo.require_run('r')['budget']['modelCalls']==1


@pytest.mark.parametrize('question,expected',[('设计一个2×2实验',1),('Design a 2x2 experiment',1),('设计三组实验',0)])
def test_server_rollout_only_selects_explicit_binary_factorial_requests(tmp_path,question,expected):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kw:None,llm_client=object(),shared_experiment_plan_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':question},start_async=False)
        assert r['experimentSharedPlanContractVersion']==expected
    finally:facade.shutdown()


def test_valid_missing_final_coverage_allows_one_repair_but_invalid_response_does_not():
    for invalid in (False,True):
        r,data,aliases=ready();r['state']['sharedExperimentInput']={'data':data,'aliases':aliases,'requiredDomains':[]}
        update=updater(r);calls=[];final_count=[0]
        def invoke(rid,node,prompt,opts,**kw):
            calls.append(node)
            if node==SCIENCE:return reply(verdict(r,data))
            if node==REPAIR:return edit_response(r)
            assert node=='verify_answer_coverage';final_count[0]+=1
            if invalid:return {'content':'null'}
            return coverage(prompt,missing=final_count[0]==1)
        verify(r,update,invoke)
        assert calls.count(REPAIR)==(0 if invalid else 1)
        assert r['state']['sharedExperimentRelease']['complete'] is (not invalid)


def test_unknown_repair_is_not_sent_twice():
    r,data,aliases=diagnosed();sent=Mock(side_effect=UnknownCallError('repair-original'))
    def save(v):r['state']['sharedExperimentRevision']=deepcopy(v)
    with pytest.raises(UnknownCallError):repair(r,data,aliases,invoke=sent,checkpoint=save)
    with pytest.raises(DeepResearchError):repair(r,data,aliases,invoke=sent,checkpoint=save)
    assert sent.call_count==1 and r['state']['sharedExperimentRevision']['status']=='invocation_failed'
