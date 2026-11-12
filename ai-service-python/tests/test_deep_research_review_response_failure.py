from copy import deepcopy
import json
from unittest.mock import Mock,patch
import pytest
from services.deep_research.contracts import DeepResearchError
from services.deep_research.review_response_failure import unresolved
from services.deep_research.coverage_repair import prepare_coverage_repair
from test_deep_research_factual_decision import checker,target,evidence,response


def run_fixture(bad,*,policy=True,isolation=True):
    calls=[]
    def invoke(**kw):
        calls.append(kw)
        if len(calls)==1:
            row=response();row['claimId']='keep';return {'content':json.dumps([row]),'finishReason':'stop'}
        if isinstance(bad,Exception):raise bad
        return bad
    c=checker(invoke,isolate_factual_claims=isolation,known_single_review_failure=policy)
    claims=[{**target(),'claimId':'keep'},{**target(),'claimId':'pending'}]
    return c,claims,calls


@pytest.mark.parametrize('bad',[{'content':'null','finishReason':'stop'}, {'content':'[]','finishReason':'stop'},
    {'content':'{}','finishReason':'stop'}, {'content':'[','finishReason':'length'}])
def test_received_invalid_single_review_keeps_prior_verdict_without_resend(bad):
    c,claims,calls=run_fixture(bad);before=deepcopy(claims)
    rows=c(claims,evidence())
    assert len(calls)==2 and rows[0]['claimId']=='keep' and rows[0]['status']=='passed'
    assert rows[1]['claimId']=='pending' and rows[1]['status']=='failed'
    assert rows[1]['executionState']=='received_invalid' and rows[1]['reviewResponseAudit']['responseState']=='received_invalid'
    assert claims==before


@pytest.mark.parametrize('policy',[False,None,0,1,'1'])
def test_no_exact_policy_keeps_old_error(policy):
    c,claims,calls=run_fixture({'content':'null'},policy=policy)
    with pytest.raises(DeepResearchError,match='事实核查'):c(claims,evidence())
    assert len(calls)==2


@pytest.mark.parametrize('code',['scope_revoked','cancelled','budget_exhausted','external_call_unknown','invalid_verification_response'])
def test_errors_before_a_received_response_are_never_converted(code):
    error=DeepResearchError(code,'Original execution error.',{'responseState':'received_invalid'})
    c,claims,calls=run_fixture(error)
    with pytest.raises(DeepResearchError) as caught:c(claims,evidence())
    assert caught.value is error and len(calls)==2


def test_valid_failed_semantic_decision_is_not_replaced_by_execution_failure():
    raw=response(False);raw['claimId']='pending'
    c,claims,calls=run_fixture({'content':json.dumps([raw]),'finishReason':'stop'})
    rows=c(claims,evidence())
    assert rows[1]['status']=='failed' and rows[1]['reason']==raw['reason']
    assert 'reviewResponseAudit' not in rows[1]


def test_response_audit_is_preserved_but_is_not_a_body_repair_instruction():
    claim={**target(),'claimId':'pending','obligationIds':['o2']}
    bad=unresolved(claim,{'content':'null','finishReason':'stop'})
    from services.deep_research.verification import verify_claims,make_evidence
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},claim['text'],claim['text'],location={},obligation_ids=[])
    ev['evidenceId']='own'
    verified=verify_claims([claim],[ev],lambda *_:[bad])
    assert verified['rejected'][0]['reviewResponseAudit']['responseState']=='received_invalid'
    report={'claims':[claim]};audit={'gaps':[{'obligationId':'o2','question':'Explain the missing point'},
        {'obligationId':'answer_scope','question':'Explain all','wholeQuestion':True}]}
    original=deepcopy((report,verified,audit))
    targets=prepare_coverage_repair(report,verified,audit,defer_invalid_reviews=True)
    assert targets['rejected']==[] and targets['deferredReviewClaims']==['pending']
    assert (report,verified,audit)==original
    assert prepare_coverage_repair(report,verified,audit)['rejected']
    other={**target(),'claimId':'bad','obligationIds':['o3']};report['claims'].append(other)
    verified['rejected'].append({'claimId':'bad','reason':'semantic_unresolved','detail':'A genuine scoped mismatch.'})
    assert [v['claimId'] for v in prepare_coverage_repair(report,verified,audit,defer_invalid_reviews=True)['rejected']]==['bad']


@pytest.mark.parametrize('phase',['observation','entailment'])
def test_partitioned_invalid_response_is_isolated_to_its_parent_claim(phase):
    from test_deep_research_partitioned_scope_review import inputs,checker_for
    claim,expression,record,ev=inputs();c,calls=checker_for(claim,expression,record,ev)
    original=c._invoke
    def invoke(**kw):
        result=original(**kw);operator='Review evidence ENTAILMENT' in kw['prompt']
        return {'content':'null','finishReason':'stop'} if operator==(phase=='entailment') else result
    c._invoke=invoke;c._known_single_review_failure=True
    rows=c([claim],ev)
    assert rows[0]['claimId']=='c' and rows[0]['status']=='failed'
    assert rows[0]['reviewResponseAudit']['responseState']=='received_invalid'
    assert len(calls)==(1 if phase=='observation' else 2)


def test_graph_publishes_prior_checked_fact_as_partial_without_rewriting_unreviewed_point():
    from services.deep_research.graph import make_verify_node,make_publish_node
    keep={**target(),'claimId':'keep','obligationIds':['o1'],'verification':'semantic_passed'}
    pending={**target(),'claimId':'pending','obligationIds':['o2']}
    row=unresolved(pending,{'content':'null','finishReason':'stop'})
    verification={'accepted':[keep],'rejected':[{'claimId':'pending','reason':'semantic_unresolved',
        'detail':row['reason'],'reviewResponseAudit':row['reviewResponseAudit'],'executionState':'received_invalid'}]}
    record={'question':'Explain both','perClaimReviewFailureContractVersion':1,
        'state':{'reportBody':{'claims':[keep,pending]},'evidence':[],'plan':[]}}
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(record);return record
    invoke=Mock(side_effect=AssertionError('No body redraft for a malformed audit'))
    audit={'status':'checked','gaps':[{'obligationId':'o2','question':'Explain point2'}]}
    with patch('services.deep_research.final_coverage.audit_final_answer',return_value=audit):
        result=make_verify_node(lambda *_:deepcopy(verification),None,update,invoke)({'run_id':'r'})
    assert result['claim_ids']==['keep'] and record['state']['deferredReviewClaims']==['pending']
    invoke.assert_not_called();publish=Mock(return_value=({'publicationId':'p'},True))
    assert make_publish_node(publish,update)({'run_id':'r'})['outcome']=='partial'
    assert record['state']['verifiedReport']['rejectedClaims'][0]['claimId']=='pending'


def test_profile_is_server_owned_frozen_and_not_retrofitted(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='perClaimReviewFailureContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1
        assert facade._make_semantic_checker(r['runId'])._known_single_review_failure() is True
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        assert facade._make_semantic_checker('old')._known_single_review_failure() is False
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,key:1})
    finally:facade.shutdown()


def test_unknown_error_does_not_even_evaluate_new_failure_policy():
    error=DeepResearchError('external_call_unknown','Keep unknown intact.')
    def invoke(**kw):raise error
    policy=Mock(side_effect=AssertionError('No policy query for unknown response'))
    c=checker(invoke,isolate_factual_claims=True,known_single_review_failure=policy)
    with pytest.raises(DeepResearchError) as caught:c([target()],evidence())
    assert caught.value is error;policy.assert_not_called()
