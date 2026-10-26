"""Observed settings are finite factual assertions, not unlabelled equations."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.partitioned_scope_review import observation_claims
from services.deep_research.scope_expression import materialize
from services.deep_research.scope_expression_review import context_for_record
from services.deep_research.tools import BudgetedSemanticChecker


def packet():
    expr={'observedSettings':[{'subject':'Method A','attribute':'SH compactness','value':'2 degrees'}],
          'notEstablished':[]}
    claim,audit=materialize({'claimId':'c','kind':'inference','text':'','conditions':{},
        'evidenceRefs':['own'],'scopeExpression':expr})
    record={'scopeExpressionReviewContractVersion':2,'state':{'synthesisScopeExpressionAudit':[audit]}}
    return claim,expr,record


def test_complete_predicate_preserves_literal_setting_and_cannot_add_a_quality_result():
    claim,expr,record=packet();before=deepcopy((claim,expr,record))
    old=observation_claims(claim,expr);new=observation_claims(claim,expr,assertions=True)
    assert old==observation_claims(claim,expr,assertions=False)
    assert old[0]['text']=='Method A，SH compactness=2 degrees'
    assert new[0]['text']=='所引来源报告，在对Method A的一项评估中，SH compactness为2 degrees。'
    assert new[0]['claimId']!=old[0]['claimId']
    assert new==observation_claims(claim,expr,assertions=True)
    assert new[0]['evidenceRefs']==claim['evidenceRefs'] and new[0]['kind']=='reported'
    assert new[0]['conditions']=={} and '质量' not in new[0]['text'] and '所有' not in new[0]['text']
    assert (claim,expr,record)==before


@pytest.mark.parametrize('supported',[False,True])
def test_real_partitioned_checker_independently_reviews_the_new_assertion(supported):
    claim,expr,record=packet();child=observation_claims(claim,expr,assertions=True)[0]
    invoke=Mock(return_value={'content':json.dumps([{'claimId':child['claimId'],
        'status':'passed' if supported else 'failed','reason':'Actual independent review result.'}])})
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_observation_assertions=lambda:True,
        scope_expression_context=lambda targets:context_for_record(record,targets))
    result=checker([claim],[{'evidenceId':'own','quote':'Method A was evaluated with degree two SH.'}])[0]
    assert result['status']==('passed' if supported else 'failed')
    assert result['partitionedScopeAudit']['observationContractVersion']==1
    assert child['text'] in invoke.call_args.kwargs['prompt'] and invoke.call_count==1


def test_old_child_verdict_identity_cannot_approve_the_new_assertion():
    claim,expr,record=packet();old=observation_claims(claim,expr)[0]
    invoke=Mock(return_value={'content':json.dumps([{'claimId':old['claimId'],'status':'passed','reason':'Old verdict'}])})
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_observation_assertions=True,scope_expression_context=lambda targets:context_for_record(record,targets))
    from services.deep_research.contracts import DeepResearchError
    try:
        result=checker([claim],[{'evidenceId':'own','quote':'Original quotation.'}])
    except DeepResearchError:
        result=[]
    assert not result or result[0]['status']=='failed'
    assert invoke.call_count==1


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_server_policy_is_immutable_and_checker_does_not_migrate_old_run(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'first','question':'核查',
            'deferStart':True,'scopeObservationContractVersion':replacement},start_async=False)
        assert run['scopeObservationContractVersion']==1
        assert facade._build_semantic_checker(run['runId'],Mock())._scope_observation_assertions() is True
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'scopeObservationContractVersion':replacement})
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('scopeObservationContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        assert facade._build_semantic_checker('old',Mock())._scope_observation_assertions() is False
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()
