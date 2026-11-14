"""Source-grounded reader input and durable resume boundaries, not model quality."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_rewrite import _prepare, rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture, answer, options

GOALS=[{'obligationId':'o','question':'解释方法记录了什么及其边界。','completionCriteria':['解释机制']}]

def targets(request):
    return json.JSONDecoder().raw_decode(request['prompt'].split('Target IDs, original kinds and source permissions (metadata, NOT scientific approval):\n')[1])[0]

def test_mapped_points_drop_draft_prose_keep_complete_sources_and_identity():
    report,ev,q=fixture();before=deepcopy((report,ev))
    old,_=_prepare(report,ev,q,contract_version=9,requirement_context=GOALS)
    new,reason=_prepare(report,ev,q,contract_version=9,requirement_context=GOALS,mapped_source_first=True)
    assert reason is None
    assert all('unverifiedPointHint' in t for t in targets(old))
    assert all('unverifiedPointHint' not in t for t in targets(new))
    for a,b in zip(targets(old),targets(new)):
        assert {k:v for k,v in a.items() if k!='unverifiedPointHint'}==b
    for e in ev:assert e['quote'] in new['prompt']
    assert report['claims'][0]['text'] not in new['prompt']
    assert (report,ev)==before and old['outputTokens']==new['outputTokens']

@pytest.mark.parametrize('ids',[[],['missing'],['o','missing']])
def test_incomplete_goal_mapping_keeps_hint_for_only_unmapped_target(ids):
    report,ev,q=fixture();report['claims'][0]['obligationIds']=ids
    new,_=_prepare(report,ev,q,contract_version=9,requirement_context=GOALS,mapped_source_first=True)
    rows=targets(new)
    assert rows[0]['unverifiedPointHint']==report['claims'][0]['text']
    assert 'unverifiedPointHint' not in rows[1]

def test_protected_budget_recursion_keeps_fixed_point_and_source_only_edit():
    report,ev,q=fixture()
    request,reason=_prepare(report,ev,q,requirement_context=GOALS,mapped_source_first=True,**options())
    assert reason is None
    assert [r['claimId'] for r in targets(request)]==['edit']
    assert 'unverifiedPointHint' not in targets(request)[0]
    assert 'Fixed answer context' in request['prompt']
    assert report['claims'][1]['text'] in request['prompt']

def test_settled_response_reused_and_protocol_change_rejected_before_dispatch():
    report,ev,q=fixture();states=[];invoke=Mock(return_value=answer())
    opts={**options(),'requirement_context':GOALS,'mapped_source_first':True}
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,**opts)
    assert states[-1]['audienceMappedSourceContractVersion']==1
    assert result['claims'][1]==report['claims'][1]
    invoke.reset_mock()
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**opts)==result
    for change in ('absent','boolean','old'):
        saved=deepcopy(states[-1]);kw=deepcopy(opts)
        if change=='old':kw.pop('mapped_source_first')
        elif change=='boolean':saved['audienceMappedSourceContractVersion']=True
        else:saved.pop('audienceMappedSourceContractVersion')
        with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=saved,**kw)
    invoke.assert_not_called()

def test_flag_is_server_owned_immutable_and_not_added_to_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='audienceMappedSourceContractVersion'
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(run[key]) is int and run[key]==4
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(run['runId'],lambda r:{**r,key:False})
        old=deepcopy(run);old.pop(key);old.update(runId='legacy',idempotencyKey='legacy');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,key:1})
    finally:facade.shutdown()
