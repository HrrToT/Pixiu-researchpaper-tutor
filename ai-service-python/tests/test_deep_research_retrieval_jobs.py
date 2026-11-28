"""Bounded concurrent tools retain identities, budget admission and cancellation."""
from threading import Barrier, Event, Lock
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.dependencies import scoped_updater
from services.deep_research.graph import make_acquire_node
from services.deep_research.retrieval_jobs import retrieve_jobs
from services.deep_research.tools import TrackedRetriever
from test_deep_research_dependencies import begin


def jobs(count=4):
    return [{'query':'question-'+str(i),'pdfId':str(i),'materialId':str(i),'obligationId':'o'+str(i)} for i in range(count)]


def test_two_tools_overlap_and_return_their_own_identity():
    barrier=Barrier(2); lock=Lock(); active=0; peak=0
    def retrieve(query,pdf_id,limit=5):
        nonlocal active,peak
        with lock: active+=1; peak=max(peak,active)
        if pdf_id in {'0','1'}: barrier.wait(timeout=5)
        with lock: active-=1
        return [{'owner':pdf_id,'query':query}]
    values=list(retrieve_jobs(jobs(),retrieve,parallel=True))
    assert peak==2 and len(values)==4
    assert all(result==[{'owner':job['pdfId'],'query':job['query']}] for job,result in values)


def test_atomic_budget_shared_by_parallel_jobs(tmp_path):
    repo=begin(tmp_path); sends=[]; lock=Lock()
    repo.update_run('r',lambda r:{**r,'budget':{**r['budget'],'maxExternalSearches':2}})
    def retrieve(query,pdf_id,limit=5):
        call,_=repo.reserve_call(run_id='r',node='acquire',tool='budgeted-fixture',args_digest=pdf_id,
                                budget_delta={'externalSearches':1})
        with lock: sends.append(pdf_id)
        repo.complete_call(call['callId'],status='succeeded',result={'items':[]},reservation_token=call['reservationToken'])
        return []
    with pytest.raises(BudgetExhaustedError):
        list(retrieve_jobs(jobs(6),retrieve,parallel=True))
    assert len(sends)==2 and repo.require_run('r')['budget']['externalSearches']==2
    assert len(repo.list_calls('r'))==2


def test_cancel_keeps_two_admitted_results_without_dispatching_remaining_jobs(tmp_path):
    repo=begin(tmp_path); barrier=Barrier(2); cancelled=Event(); sends=[]; lock=Lock()
    def base(query,pdf_id,limit=5):
        with lock: sends.append(pdf_id)
        barrier.wait(timeout=5)
        if pdf_id=='0':
            repo.update_run('r',lambda r:{**r,'status':'cancelled'})
            cancelled.set()
        else: assert cancelled.wait(timeout=5)
        return [{'sourceId':'s'+pdf_id,'sourceWorkId':pdf_id,'text':'original '+pdf_id}]
    tracked=TrackedRetriever(base,lambda *_:True,repo.reserve_call,
        lambda call_id,**kwargs:repo.complete_call(call_id,allow_late=True,**kwargs))
    values=list(retrieve_jobs(jobs(6),lambda query,pdf_id,limit=5:tracked('r',query,pdf_id,limit=limit),
        parallel=True,allowed=lambda:repo.require_run('r')['status']=='running'))
    assert set(sends)=={'0','1'} and len(values)==2
    assert repo.require_run('r')['status']=='cancelled'
    assert len(repo.list_calls('r'))==2 and all(c['status']=='succeeded' for c in repo.list_calls('r'))


def test_observed_failure_does_not_admit_later_jobs():
    sends=[]
    def retrieve(query,pdf_id,limit=5):
        sends.append(pdf_id)
        if pdf_id=='0': raise DeepResearchError('fixture_unknown','Do not retry')
        return []
    with pytest.raises(DeepResearchError,match='retry'):
        list(retrieve_jobs(jobs(6),retrieve,parallel=True))
    assert '0' in sends and set(sends).issubset({'0','1'})


def test_same_source_id_with_different_text_is_not_merged(tmp_path):
    repo=begin(tmp_path)
    def retrieve(query,pdf_id,limit=5):
        return [{'sourceId':'same','sourceWorkId':'p','text':query,'accessLevel':'fulltext'}]
    node=make_acquire_node(retrieve,lambda *_:True,scoped_updater(repo.update_run))
    with pytest.raises(DeepResearchError,match='不同原文'):
        node({'run_id':'r'})
    assert not repo.require_run('r')['state'].get('sources')


def test_source_and_obligation_order_do_not_depend_on_tool_completion_order(tmp_path):
    repo=begin(tmp_path); barrier=Barrier(2)
    def retrieve(query,pdf_id,limit=5):
        barrier.wait(timeout=5)
        key='z' if 'Research A' in query else 'a'
        return [{'sourceId':key,'sourceWorkId':'p','text':'stable '+key,'accessLevel':'fulltext'}]
    node=make_acquire_node(retrieve,lambda *_:True,scoped_updater(repo.update_run))
    node({'run_id':'r'})
    sources=repo.require_run('r')['state']['sources']
    assert [(s['sourceId'],s['obligationIds']) for s in sources]==[('a',['o-B']),('z',['o-A'])]


@pytest.mark.parametrize('status',['queued','paused','cancelled'])
def test_nonrunning_frontier_never_dispatches_retrieval(tmp_path,status):
    repo=begin(tmp_path,start=status!='queued')
    if status!='queued':
        repo.transition('r',status)
    retrieve=Mock(return_value=[])
    make_acquire_node(retrieve,lambda *_:True,scoped_updater(repo.update_run))({'run_id':'r'})
    retrieve.assert_not_called()
    assert repo.require_run('r')['status']==status and not repo.list_calls('r')
