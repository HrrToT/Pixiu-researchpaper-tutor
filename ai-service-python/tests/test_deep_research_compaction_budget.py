"""Rendered scope and fixed points consume the same human character limit."""
from copy import deepcopy
import json
from unittest.mock import Mock,patch

import pytest

from services.deep_research.answer_constraints import visible_count
from services.deep_research.compaction_budget import guidance
from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.scope_compaction import compact
from test_deep_research_scope_compaction import packet


def budget(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Server-measured publication budget (capacity metadata, NOT paper facts):\n',1)[1])[0]


@pytest.mark.parametrize('fixed',[[],[{'claimId':'kept','kind':'reported','text':'保留的条件。'*5,'conditions':{},'evidenceRefs':['other']}]])
def test_actual_renderer_reserves_existing_scope_and_fixed_points_before_prose(fixed):
    report,audits,response=packet();before=deepcopy((report,audits,fixed));invoke=Mock(return_value={'content':json.dumps(response)})
    out,new=compact(report,audits,'300字以内',invoke,json.loads,presentation_version=2,fixed_claims=fixed,budget_guidance=True)
    assert out and new[0]['verification']=='unchecked'
    measured=budget(invoke.call_args.args[0]);blank={**report,'claims':[{**c,'text':'','conditions':{}} for c in report['claims']]}
    reserved={**report,'claims':[{**report['claims'][0],'text':'','conditions':{}},report['claims'][1]]}
    count=lambda p:visible_count({**p,'claims':[*fixed,*p['claims']]},300,presentation_version=2)
    assert measured['ordinaryProseSharedCharactersIfScopeUnchanged']==max(0,300-count(reserved))
    assert measured['fixedDisplayAndAcceptedCharacters']==count(blank)
    assert measured['currentCompleteCharacters']==count(report)
    assert measured['currentScopeReserveCharacters']==count(reserved)-count(blank)
    assert count(out)<=300 and measured['totalCharacters']==300
    assert (report,audits,fixed)==before and invoke.call_count==1


def test_multiple_prose_points_share_one_allowance_not_one_allowance_each():
    report,audits,_=packet();report['claims'].insert(1,{**report['claims'][0],'claimId':'f2','text':'另一段。'*40})
    count=lambda p:visible_count(p,300,presentation_version=2)
    measured=budget(guidance(report,{'c'},count,300))
    assert [x['kind'] for x in measured['pointMeasurements']]==['prose','prose','scope']
    blank={**report,'claims':[c if c['claimId']=='c' else {**c,'text':'','conditions':{}} for c in report['claims']]}
    assert measured['ordinaryProseSharedCharactersIfScopeUnchanged']==max(0,300-count(blank))


@pytest.mark.parametrize('mutation',['oversize','drop','foreign','change_quantifier','truncated'])
def test_budget_guidance_does_not_relax_length_identity_or_scope_guards(mutation):
    report,audits,response=packet()
    if mutation=='oversize':response['claims'][0]['text']='长'*400
    elif mutation=='drop':response['claims'].pop()
    elif mutation=='foreign':response['claims'][0]['evidenceRefs']=['foreign']
    elif mutation=='change_quantifier':response['claims'][1]['scopeExpression']['notEstablished'][0]['quantifier']='exists'
    invoke=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mutation=='truncated' else 'stop'})
    out,new=compact(report,audits,'300字以内',invoke,json.loads,presentation_version=2,budget_guidance=True)
    assert out is None and new==audits and invoke.call_count==1


def test_policy_off_keeps_original_request_and_result_exact():
    report,audits,response=packet();calls=[]
    def invoke(prompt):calls.append(prompt);return {'content':json.dumps(response)}
    old=compact(report,audits,'300字以内',invoke,json.loads,presentation_version=2)
    new=compact(report,audits,'300字以内',invoke,json.loads,presentation_version=2,budget_guidance=False)
    assert old==new and calls[0]==calls[1] and 'Server-measured publication budget' not in calls[0]


@pytest.mark.parametrize('bad',[None,0,1,'1'])
def test_policy_types_are_strict_before_any_model_call(bad):
    report,audits,_=packet();invoke=Mock()
    with pytest.raises(ValueError):compact(report,audits,'300字以内',invoke,json.loads,budget_guidance=bad)
    with pytest.raises(ValueError):compact_repairs(report,report['claims'],[],{},'300字以内',invoke,json.loads,budget_guidance=bad)
    invoke.assert_not_called()


def test_saved_legacy_request_cannot_switch_to_new_prompt_or_resubmit():
    report,audits,response=packet();invoke=Mock(return_value={'content':json.dumps(response)});states=[]
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'300字以内',invoke,json.loads)
    compact_repairs(*args,checkpoint=states.append)
    invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='输入不一致'):compact_repairs(*args,saved=states[-1],budget_guidance=True)
    invoke.assert_not_called()


@pytest.mark.parametrize('value',[1,True,None,0,'1'])
def test_actual_graph_wires_strict_root_policy_and_still_reverifies_all_edits(value):
    from services.deep_research.graph import make_verify_node
    report,audits,response=packet();report['sections']=[]
    kept={'claimId':'kept','kind':'reported','text':'保留。','conditions':{},'evidenceRefs':['e']}
    initial={'accepted':[kept],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in report['claims']]}
    record={'question':'300字以内','compactionBudgetContractVersion':value,'repairCompactionContractVersion':1,
        'scopeCompactionContractVersion':1,'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,'reportPresentationContractVersion':2,
        'state':{'outputKind':'claim_verification','reportBody':report,'repairReport':report,'repairAttempted':True,
            'initialVerification':initial,'repairTargets':initial,'initialAnswerCoverage':{'status':'not_requested','gaps':[]},
            'evidence':[],'repairBatchState':{'scopeExpressionAudit':{'0':audits}}}}
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(response)})
    verifier=Mock(side_effect=lambda rows,*_: {'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in rows]})
    with patch('services.deep_research.repair.repair_rejected',return_value=report['claims']):
        make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
    assert invoke.call_count==1
    prompt=invoke.call_args.args[2]
    assert ('Server-measured publication budget' in prompt) is (type(value) is int and value==1)
    assert [c['claimId'] for c in verifier.call_args.args[0]]==['f','c']
    assert record['state']['verifiedReport']['verifiedClaims']==[kept]


def test_factory_owns_immutable_budget_contract_and_legacy_rows_stay_unchanged(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    key='compactionBudgetContractVersion';repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',key:False},start_async=False)
        assert type(row[key]) is int and row[key]==1
        old=deepcopy(row);old.pop(key);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        for rid in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,key:2})
        assert key not in repo.require_run('old')
    finally:facade.shutdown()
