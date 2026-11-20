"""Complete repair candidates reach compaction and then independent verification."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.repair import repair_rejected
from services.deep_research.repair_compaction import compact_repairs, enabled
from services.deep_research.scope_expression_review import context_for_record
from test_deep_research_scope_compaction import packet


def test_deferred_filter_preserves_both_targets_and_has_separate_resume_identity():
    claims=[{'claimId':k,'kind':'reported','text':'bad','evidenceRefs':['e']} for k in ('large','small')]
    revisions=[{**claims[0],'text':'a'*101},{**claims[1],'text':'known'}]
    states=[];invoke=Mock(return_value={'content':json.dumps(revisions)})
    args=({'claims':claims},{'accepted':[],'rejected':[{'claimId':c['claimId']} for c in claims]},
          [{'evidenceId':'e','quote':'known'}],'100字以内',invoke,json.loads)
    assert len(repair_rejected(*args,defer_length_filter=True,checkpoint=states.append))==2
    assert 'omittedForLength' not in states[-1]
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert len(repair_rejected(*args,defer_length_filter=True,batch_state=saved))==2
    invoke.assert_not_called()
    with pytest.raises(Exception,match='修订计划'):
        repair_rejected(*args,batch_state=saved)
    invoke.assert_not_called()


def test_joint_repair_keeps_accepted_fixed_and_replaces_scope_context_without_approval():
    report,audits,response=packet()
    accepted=[{'claimId':'accepted','kind':'reported','text':'已核对的短结论。','conditions':{},'evidenceRefs':['e']}]
    report['sections']=[]
    before=deepcopy((report,audits,accepted));states=[]
    invoke=Mock(return_value={'content':json.dumps(response)})
    revised=compact_repairs(report,report['claims'],accepted,{'scopeExpressionAudit':{'0':audits}},
        '300字以内',invoke,json.loads,presentation_version=2,checkpoint=states.append)
    assert [c['claimId'] for c in revised]==['f','c']
    assert (report,audits,accepted)==before
    assert states[-1]['status']=='completed' and states[-1]['scopeExpressionAudit'][0]['verification']=='unchecked'
    record={'repairCompactionContractVersion':1,'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,
            'state':{'repairCompaction':states[-1]}}
    assert 'c' in context_for_record(record,revised)
    assert not context_for_record({**record,'repairCompactionContractVersion':0},revised)
    from services.deep_research.answer_constraints import visible_count
    assert visible_count({'claims':accepted+revised},300,presentation_version=2)<=300
    invoke.reset_mock()
    assert compact_repairs(report,report['claims'],accepted,{'scopeExpressionAudit':{'0':audits}},
        '300字以内',invoke,json.loads,presentation_version=2,saved=states[-1])==revised
    invoke.assert_not_called()
    from services.deep_research.verification import verify_claims
    assert not verify_claims(revised,[])['accepted']


@pytest.mark.parametrize('mode',['invalid','unknown','budget'])
def test_compaction_failure_never_promotes_or_automatically_resends(mode):
    from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
    report,audits,_=packet();states=[]
    invoke=Mock(return_value={'content':'{}'})
    if mode=='unknown':invoke.side_effect=DeepResearchError('call_unknown','unknown')
    if mode=='budget':invoke.side_effect=BudgetExhaustedError('modelCalls',18,19)
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'300字以内',invoke,json.loads)
    if mode=='invalid':
        assert compact_repairs(*args,checkpoint=states.append)==[]
        assert states[-1]['status']=='invalid'
        invoke.reset_mock()
        assert compact_repairs(*args,saved=states[-1])==[]
        invoke.assert_not_called()
    else:
        with pytest.raises((DeepResearchError,BudgetExhaustedError)):
            compact_repairs(*args,checkpoint=states.append)
        assert states[-1]['status']=='pending' and 'claims' not in states[-1]
        assert invoke.call_count==1


def test_graph_compacts_all_repairs_and_verifies_new_text_with_readonly_accepted_claim():
    from services.deep_research.graph import make_verify_node
    report,audits,response=packet();report['sections']=[]
    accepted={'claimId':'kept','kind':'reported','text':'保留。','evidenceRefs':['e'],'conditions':{}}
    initial={'accepted':[accepted],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in report['claims']]}
    record={'question':'300字以内','repairCompactionContractVersion':1,'scopeCompactionContractVersion':1,
        'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,'reportPresentationContractVersion':2,
        'state':{'outputKind':'claim_verification','reportBody':report,'repairReport':report,'repairAttempted':True,
          'initialVerification':initial,'repairTargets':initial,'initialAnswerCoverage':{'status':'not_requested','gaps':[]},
          'evidence':[],'repairBatchState':{'scopeExpressionAudit':{'0':audits}}}}
    def update(_id,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(response)})
    verifier=Mock(side_effect=lambda rows,*_: {'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in rows]})
    # Raw repair generation is already independently tested; exercise the actual
    # graph handoff with all candidates, including a previously oversized scope.
    from unittest.mock import patch
    with patch('services.deep_research.repair.repair_rejected',return_value=report['claims']) as repair:
        make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
    assert repair.call_args.kwargs['defer_length_filter'] is True
    assert invoke.call_count==1 and invoke.call_args.args[1]=='synthesize_compact'
    checked=verifier.call_args.args[0]
    assert [c['claimId'] for c in checked]==['f','c'] and checked[0]['text']==response['claims'][0]['text']
    assert record['state']['verifiedReport']['verifiedClaims']==[accepted]
    assert record['state']['repairCompaction']['scopeExpressionAudit'][0]['renderedText']==checked[1]['text']
    invoke.reset_mock();verifier.reset_mock()
    make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
    invoke.assert_not_called();verifier.assert_not_called()


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_new_policy_is_server_owned_immutable_and_legacy_disabled(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'repairCompactionContractVersion':replacement},start_async=False)
        run['state']['outputKind']='claim_verification'
        assert enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'repairCompactionContractVersion':replacement})
        legacy=deepcopy(run);legacy.pop('repairCompactionContractVersion')
        assert not enabled(legacy)
    finally:facade.shutdown()
