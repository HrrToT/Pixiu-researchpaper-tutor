"""Stopped unknown work remains unknown; child runs cannot bypass the ledger."""
import pytest

from services.deep_research.contracts import UnresolvedUnknownError
from test_deep_research_end_to_end import make_facade, create


class UnknownModel:
    calls = 0
    def invoke(self, request):
        from llm.provider import LLMProviderError
        self.calls += 1
        raise LLMProviderError('fixture timeout',provider='fixture',model='fixture',retryable=True)


@pytest.mark.parametrize('entry',['create','continue'])
def test_cancelled_unknown_cannot_start_a_child_from_either_entry(tmp_path,entry):
    model=UnknownModel();repo,facade,_=make_facade(tmp_path,model)
    try:
        parent=create(facade);rid=parent['runId'];repo.begin_execution(rid);facade._execute_graph(rid)
        paused=facade.get(rid)
        cancelled=facade.action(rid,'cancel',{'requestId':'cancel','expectedRunRevision':paused['runRevision']})
        before=repo.list_calls(rid)
        assert cancelled['status']=='cancelled'
        assert 'continue' not in cancelled['allowedActions']
        assert cancelled['activity'] is None
        with pytest.raises(UnresolvedUnknownError):
            if entry=='create':
                facade.create({'workspaceTaskId':'workspace','operationKey':'child',
                    'question':parent['question'],'parentRunId':rid,'deferStart':True},start_async=False)
            else:
                facade.action(rid,'continue',{'requestId':'child','expectedRunRevision':cancelled['runRevision'],
                    'deferStart':True})
        assert len(repo.list_runs())==1 and repo.list_calls(rid)==before
        assert model.calls==1 and before[0]['status']=='unknown' and before[0]['settled'] is False
    finally:facade.shutdown()


def test_cancelled_pending_dispatch_is_not_advertised_as_safe_to_continue(tmp_path,monkeypatch):
    model=UnknownModel();repo,facade,_=make_facade(tmp_path,model)
    try:
        parent=create(facade);rid=parent['runId'];repo.begin_execution(rid)
        repo.reserve_call(run_id=rid,node='verify',tool='llm_invoke',args_digest='pending')
        def forbid_response_loading(*args):
            raise AssertionError('Status projection must not load full model responses')
        monkeypatch.setattr(repo,'list_calls',forbid_response_loading)
        cancelled=facade.action(rid,'cancel',{'requestId':'cancel','expectedRunRevision':repo.require_run(rid)['runRevision']})
        assert cancelled['errorCode']=='unresolved_unknown'
        assert 'continue' not in cancelled['allowedActions']
        with pytest.raises(UnresolvedUnknownError):
            facade.create({'workspaceTaskId':'workspace','operationKey':'child','question':parent['question'],
                'parentRunId':rid,'deferStart':True},start_async=False)
        assert model.calls==0 and len(repo.list_runs())==1
    finally:facade.shutdown()


def test_safely_cancelled_work_keeps_explicit_followup_available(tmp_path):
    model=UnknownModel();repo,facade,_=make_facade(tmp_path,model)
    try:
        parent=create(facade);rid=parent['runId']
        cancelled=facade.action(rid,'cancel',{'requestId':'cancel','expectedRunRevision':parent['runRevision']})
        assert 'continue' in cancelled['allowedActions']
        child=facade.action(rid,'continue',{'requestId':'child','expectedRunRevision':cancelled['runRevision'],
            'question':'另一个明确问题','deferStart':True})
        assert child['parentRunId']==rid and len(repo.list_runs())==2 and model.calls==0
    finally:facade.shutdown()
