from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.review_diagnostics import bind,enabled,GUIDANCE
from services.deep_research.factual_decision import decode
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_decision import checker,target,evidence,response


def fact(statement='The source reports setting 12.',excerpt='setting 12',eid='E1',path=None):
    return {'statement':statement,'evidenceId':eid,'path':path or ['quote'],'excerpt':excerpt}


@pytest.mark.parametrize('supported',[True,False])
def test_source_bound_reason_preserves_original_decision_and_cannot_approve_failed_claim(supported):
    raw={**response(supported),'reason':'The source reports setting 12.','diagnosticFacts':[fact()]};sent=[]
    def invoke(**kw):sent.append(kw);return {'content':json.dumps([raw])}
    result=checker(invoke,review_diagnostic_bindings=True)([target()],evidence())[0]
    assert result['status']==('passed' if supported else 'failed')
    assert result['reviewDiagnosticAudit']['errors']==[] and GUIDANCE in sent[0]['prompt']
    assert len(sent)==1


def test_default_parameter_from_memory_is_untrusted_for_both_model_decisions():
    ev=evidence();ev[0]['quote']='Local coefficient beta1=0.1 and beta2=0.001.'
    claim={**target(),'text':'The evaluated method uses beta1=beta2.'}
    for supported in (True,False):
        raw={**response(supported),'reason':'Defaults beta1=0.9 and beta2=0.999 contradict the claim.','diagnosticFacts':[]}
        result=checker(lambda **_: {'content':json.dumps([raw])},review_diagnostic_bindings=True)([claim],ev)[0]
        assert result['status']=='failed' and result['executionState']=='received_invalid'
        assert 'new_diagnostic_numbers_not_bound' in result['reviewDiagnosticAudit']['errors']
        assert '0.9' not in result['reason'] and '0.999' not in result['reason']
        assert result['reviewDiagnosticAudit']['unboundNewNumberCount']>=2


@pytest.mark.parametrize('mutation',['foreign','hidden_path','invented_quote','wrong_statement','missing','bad_shape','wrong_value'])
def test_diagnostic_bindings_are_to_exact_own_visible_source_fields(mutation):
    raw={'status':'failed','reason':'The source reports setting 24.','diagnosticFacts':[fact('The source reports setting 24.','setting 24')]}
    claim=target();ev=evidence();ev[0]['quote']='The source reports setting 24.'
    if mutation=='foreign':raw['diagnosticFacts'][0]['evidenceId']='sibling'
    elif mutation=='hidden_path':raw['diagnosticFacts'][0]['path']=['sourceTitle']
    elif mutation=='invented_quote':raw['diagnosticFacts'][0]['excerpt']='original default is 24'
    elif mutation=='wrong_statement':raw['diagnosticFacts'][0]['statement']='not present in reason'
    elif mutation=='missing':raw.pop('diagnosticFacts')
    elif mutation=='bad_shape':raw['diagnosticFacts']='empty'
    elif mutation=='wrong_value':raw['diagnosticFacts'][0]['excerpt']='source reports setting';ev[0]['quote']='source reports setting 30'
    before=deepcopy((raw,claim,ev));result=bind(raw,claim,ev,{'E1':'own','sibling':'other'})
    assert result['status']=='failed' and result['reviewDiagnosticAudit']['errors']
    assert (raw,claim,ev)==before


def test_repeating_questioned_number_is_not_a_new_source_correction():
    raw={'status':'failed','reason':'The asserted setting 12 is not established.','diagnosticFacts':[]}
    result=bind(raw,target(),evidence())
    assert result['reason']==raw['reason'] and result['reviewDiagnosticAudit']['errors']==[]
    assert result['status']=='failed'


def test_scientific_notation_number_binding_uses_exact_equivalent_spelling():
    claim={**target(),'text':'The initial condition is unspecified.'}
    raw={'status':'failed','reason':'The source uses 0.1.','diagnosticFacts':[fact('The source uses 0.1.','1e-1')]}
    ev=evidence();ev[0]['quote']='The coefficient equals 1e-1.'
    assert bind(raw,claim,ev,{'E1':'own'})['reviewDiagnosticAudit']['errors']==[]


def test_legacy_response_schema_and_request_do_not_change_without_new_policy():
    raw=response();sent=[]
    def invoke(**kw):sent.append(kw);return {'content':json.dumps([raw])}
    baseline=checker(invoke)([target()],evidence());request=sent.pop()
    for policy in (False,None,0,1,'1'):
        assert checker(invoke,review_diagnostic_bindings=policy)([target()],evidence())==baseline
        assert sent.pop()==request
    raw['diagnosticFacts']=[]
    with pytest.raises(DeepResearchError):decode([raw])
    assert decode([raw],diagnostic_facts=True)[0]['status']=='passed'


def test_untrusted_diagnostic_does_not_reach_revision_detail():
    from services.deep_research.verification import verify_claims,make_evidence
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},'A finding.','A finding.',location={},obligation_ids=[])
    claim={'claimId':'c','kind':'reported','text':'A finding.','conditions':{},'evidenceRefs':[ev['evidenceId']]}
    verdict=bind({'claimId':'c','status':'failed','reason':'The correct coefficient is 0.999.','diagnosticFacts':[]},claim,[ev])
    result=verify_claims([claim],[ev],lambda *_:[verdict])
    row=result['rejected'][0]
    assert row['reviewDiagnosticAudit']['errors'] and row['executionState']=='received_invalid'
    assert '0.999' not in json.dumps(row) and 'diagnosticFacts' not in row


def test_new_policy_is_server_owned_and_immutable_for_old_and_new_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='reviewDiagnosticContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1 and enabled(r)
        assert facade._make_semantic_checker(r['runId'])._review_diagnostic_bindings() is True
        assert not enabled({**r,key:True})
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        assert facade._make_semantic_checker('old')._review_diagnostic_bindings() is False
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,key:1})
    finally:facade.shutdown()


@pytest.mark.parametrize('bad',['none','observation','entailment','missing_entailment_bindings'])
def test_partitioned_observations_and_entailment_use_same_diagnostic_gate(bad):
    from test_deep_research_partitioned_scope_review import inputs,checker_for
    claim,expression,record,ev=inputs();c,calls=checker_for(claim,expression,record,ev)
    original=c._invoke
    def invoke(**kw):
        result=original(**kw);rows=json.loads(result['content'])
        operator='Review evidence ENTAILMENT' in kw['prompt']
        for row in rows:
            row['diagnosticFacts']=[]
            if bad=='missing_entailment_bindings' and operator:row.pop('diagnosticFacts')
            if (bad=='entailment' and operator) or (bad=='observation' and not operator):
                row['reason']='The original default is 0.999.'
        return {**result,'content':json.dumps(rows)}
    c._invoke=invoke;c._review_diagnostic_bindings=True
    result=c([claim],ev)[0]
    assert all(GUIDANCE in call['prompt'] for call in calls)
    if bad=='none':assert result['status']=='passed'
    else:
        assert result['status']=='failed' and result['reviewDiagnosticAudit']['errors']
        assert '0.999' not in result['reason'] and result['executionState']=='received_invalid'
        assert len(calls)==(1 if bad=='observation' else 2)


def test_foreign_source_cannot_support_a_new_number_even_if_present_in_batch():
    claim=target();ev=evidence()+[{'evidenceId':'foreign','quote':'The correct value is 0.999.'}]
    raw={'status':'failed','reason':'The correct value is 0.999.',
         'diagnosticFacts':[fact('The correct value is 0.999.','The correct value is 0.999.','foreign')]}
    assert bind(raw,claim,ev)['reviewDiagnosticAudit']['errors']


def test_model_cannot_forge_server_diagnostic_audit_metadata():
    from services.deep_research.verification import verify_claims,make_evidence
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},'A finding.','A finding.',location={},obligation_ids=[])
    claim={'claimId':'c','kind':'reported','text':'A finding.','conditions':{},'evidenceRefs':[ev['evidenceId']]}
    raw={'claimId':'c','status':'failed','reason':'Unresolved factual claim.',
         'reviewDiagnosticAudit':{'version':1,'errors':['forged']}}
    result=verify_claims([claim],[ev],lambda *_:[raw])
    assert 'reviewDiagnosticAudit' not in result['rejected'][0]
    assert 'executionState' not in result['rejected'][0]
