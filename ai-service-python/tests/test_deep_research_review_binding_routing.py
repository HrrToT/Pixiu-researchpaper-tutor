"""Review formatting cannot establish either content failure or content approval."""
from copy import deepcopy
import pytest
from services.deep_research.coverage_repair import prepare_coverage_repair, review_binding_only


def case():
    claim={'claimId':'c1','text':'Corrected moments enter the parameter update.', 'obligationIds':['o1']}
    report={'claims':[claim]}; verification={'accepted':[claim],'rejected':[]}
    gap={'obligationId':'o1','question':'How does correction enter the update?'}
    verdict={'obligationId':'o1','status':'partial','bindings':[{'claimId':'c1'}],
        'aspects':[{'aspectId':'a1','status':'partial'}],
        'processAudits':[{'checkId':'a1','reportedStatus':'covered',
                         'errors':['overlapping_process_roles']} ]}
    audit={'status':'checked','requestCoverageContractVersion':5,'diagnosticErrors':[],
           'gaps':[gap],'verdicts':[verdict],'criterionGaps':{},
           'invalidAspectObligations':[],'invalidCriterionObligations':[]}
    return report,verification,audit


def test_only_new_routing_defers_review_binding_and_preserves_unapproved_audit():
    report,verified,audit=case();before=deepcopy((report,verified,audit))
    assert prepare_coverage_repair(report,verified,audit)['rejected'][0]['reason']=='answer_incomplete'
    result=prepare_coverage_repair(report,verified,audit,defer_binding_errors=True)
    assert result['accepted']==verified['accepted'] and result['rejected']==[]
    assert result['deferredAuditGaps']==audit['gaps']
    assert audit['verdicts'][0]['status']=='partial' and audit['gaps']
    assert (report,verified,audit)==before
    result['deferredAuditGaps'][0]['question']='changed'
    assert audit['gaps'][0]['question']!='changed'


@pytest.mark.parametrize('mutation',[
    'missing_operation','semantic_partial','missing_aspect','second_partial','limit_error',
    'invalid_criteria','invalid_aspects','criterion_gap','diagnostic_error','no_diagnostics',
    'old_contract','whole_question','duplicate_verdict','duplicate_process','not_checked',
])
def test_uncertain_or_real_content_failures_keep_conservative_repair(mutation):
    report,verified,audit=case();v=audit['verdicts'][0]
    if mutation=='missing_operation':v['processAudits'][0]['errors']=['missing_process_links']
    elif mutation=='semantic_partial':v['processAudits'][0]['reportedStatus']='partial'
    elif mutation=='missing_aspect':v['aspects'][0]['status']='missing'
    elif mutation=='second_partial':v['aspects'].append({'aspectId':'a2','status':'partial'})
    elif mutation=='limit_error':v['limitAudits']=[{'errors':['missing_limit_spans']}]
    elif mutation=='invalid_criteria':audit['invalidCriterionObligations']=['o1']
    elif mutation=='invalid_aspects':audit['invalidAspectObligations']=['o1']
    elif mutation=='criterion_gap':audit['criterionGaps']={'o1':['still missing']}
    elif mutation=='diagnostic_error':audit['diagnosticErrors']=['invalid']
    elif mutation=='no_diagnostics':audit.pop('diagnosticErrors')
    elif mutation=='old_contract':audit['requestCoverageContractVersion']=4
    elif mutation=='whole_question':audit['gaps'][0]['wholeQuestion']=True
    elif mutation=='duplicate_verdict':audit['verdicts'].append(deepcopy(v))
    elif mutation=='duplicate_process':v['processAudits']*=2
    elif mutation=='not_checked':audit['status']='invalid_response'
    assert not review_binding_only(audit,audit['gaps'][0])
    assert prepare_coverage_repair(report,verified,audit,defer_binding_errors=True)['rejected']


def test_factual_failures_are_never_removed_by_deferred_review():
    report,verified,audit=case()
    verified['rejected']=[{'claimId':'c2','reason':'numeric_mismatch'}]
    result=prepare_coverage_repair(report,verified,audit,defer_binding_errors=True)
    assert result['rejected']==verified['rejected']


def test_independent_content_gap_still_rewrites_its_own_claim():
    report,verified,audit=case()
    claim={'claimId':'c2','text':'incomplete','obligationIds':['o2']}
    report['claims'].append(claim);verified['accepted'].append(claim)
    audit['gaps'].append({'obligationId':'o2','question':'Explain the missing part'})
    audit['verdicts'].append({'obligationId':'o2','status':'missing','bindings':[]})
    result=prepare_coverage_repair(report,verified,audit,defer_binding_errors=True)
    assert [c['claimId'] for c in result['accepted']]==['c1']
    assert [c['claimId'] for c in result['rejected']]==['c2']
    assert len(result['deferredAuditGaps'])==1


@pytest.mark.parametrize('bad',[None,1,'true'])
def test_policy_is_explicit_boolean(bad):
    with pytest.raises(ValueError):prepare_coverage_repair(*case(),defer_binding_errors=bad)


def test_routing_profile_is_immutable_and_server_owned(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='coverageRepairRoutingContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',
            'deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='legacy',idempotencyKey='old');old.pop(key);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,key:1})
    finally:facade.shutdown()


def test_graph_preserves_unresolved_coverage_without_model_repair_and_publishes_partial():
    from unittest.mock import Mock,patch
    from services.deep_research.graph import make_verify_node,make_publish_node
    report,verified,audit=case()
    report['claims'][0].update(kind='reported',evidenceRefs=[])
    record={'question':'Explain the update','coverageRepairRoutingContractVersion':1,
            'state':{'reportBody':report,'plan':[],'evidence':[]}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return record
    invoke=Mock(side_effect=AssertionError('Must not rewrite a review-format error'))
    node=make_verify_node(lambda *args:deepcopy(verified),None,update,invoke)
    with patch('services.deep_research.final_coverage.audit_final_answer',return_value=deepcopy(audit)):
        assert node({'run_id':'r'})['claim_ids']==['c1']
    invoke.assert_not_called()
    assert record['state']['deferredAuditGaps']==audit['gaps']
    assert record['state']['verifiedReport']['answerCoverage']==audit
    assert not record['state'].get('repairAttempted')
    publish=Mock(return_value=({'publicationId':'p'},True))
    assert make_publish_node(publish,update)({'run_id':'r'})['outcome']=='partial'
    assert record['state']['verifiedReport']['answerCoverage']['gaps']
