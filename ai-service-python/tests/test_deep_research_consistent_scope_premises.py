from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.scope_expression_review import validate
from services.deep_research.partitioned_scope_review import consistent_premises_enabled
from test_deep_research_scope_expression_review import fixture,verdict
from test_deep_research_partitioned_scope_review import inputs,checker_for


def test_redundant_binding_requires_same_visible_field_without_mutating_raw_or_legacy_policy():
    claim,expression,record,evidence=fixture();result=verdict(expression)
    premise=result['scopeExpressionAudit']['notEstablished'][0]['premises'][0]
    premise['quote']='comparable quality at setting 66%.'
    before=deepcopy((claim,expression,result,evidence))
    assert validate(claim,expression,result,evidence)==['scope_expression_premises_not_bound']
    assert not validate(claim,expression,result,evidence,consistent_premises=True)
    assert (claim,expression,result,evidence)==before


@pytest.mark.parametrize('mutation',[
    'other_field','foreign','missing','bad_path','metadata','empty','non_string',
    'extra_key','spliced','changed_number','missing_path','invalid_id',
])
def test_conflicting_or_ambiguous_redundant_bindings_remain_rejected(mutation):
    claim,expression,record,evidence=fixture();result=verdict(expression)
    premise=result['scopeExpressionAudit']['notEstablished'][0]['premises'][0]
    premise['quote']='comparable quality at setting 66%.'
    if mutation=='other_field':premise['quote']='At setting 70% quality declined.'
    elif mutation=='foreign':
        evidence.append({'evidenceId':'foreign','quote':premise['quote']});premise['evidenceId']='foreign'
    elif mutation=='missing':premise['evidenceId']='missing'
    elif mutation=='bad_path':premise['path']=['sourceContext','before']
    elif mutation=='metadata':premise['path']=['location','section']
    elif mutation=='empty':premise['quote']=' '
    elif mutation=='non_string':premise['quote']=['comparable quality at setting 66%.']
    elif mutation=='extra_key':premise['approved']=True
    elif mutation=='spliced':premise['quote']='We observed at setting 66%.'
    elif mutation=='changed_number':premise['quote']='comparable quality at setting 70%.'
    elif mutation=='missing_path':premise['path']=None
    else:premise['evidenceId']=['real']
    assert validate(claim,expression,result,evidence,consistent_premises=True)


def test_context_excerpt_is_bound_to_its_actual_named_field_not_another_context_member():
    claim,expression,record,evidence=fixture();result=verdict(expression)
    evidence[0]['sourceContext']={'before':'Before condition.','after':'After observation.'}
    premise=result['scopeExpressionAudit']['notEstablished'][0]['premises'][0]
    premise.update(path=['sourceContext','before'],quote='Before condition.')
    assert not validate(claim,expression,result,evidence,consistent_premises=True)
    premise['quote']='After observation.'
    assert validate(claim,expression,result,evidence,consistent_premises=True)


def test_consistency_only_normalizes_whitespace_and_does_not_change_other_audit_schemas():
    claim,expression,record,evidence=fixture();result=verdict(expression)
    evidence[0]['quote']='We observed comparable\nquality at setting 66%.'
    premise=result['scopeExpressionAudit']['notEstablished'][0]['premises'][0]
    premise['quote']='comparable quality at setting 66%.'
    assert not validate(claim,expression,result,evidence,consistent_premises=True)
    from services.deep_research.audit_source_fields import resolve
    assert resolve(premise,{'real':evidence[0]}) is None
    premise['quote']='Comparable quality at setting 66%.'
    assert validate(claim,expression,result,evidence,consistent_premises=True)


@pytest.mark.parametrize('field,value',[
    ('relation','entailed'),('relation','undetermined'),('quantification','ambiguous'),
    ('isNegation',True),('authorOmission',True),('reason',''),('proposition','another proposition')])
def test_consistent_source_binding_never_overrides_failed_semantic_or_scope_decision(field,value):
    claim,expression,record,evidence=fixture();result=verdict(expression)
    boundary=result['scopeExpressionAudit']['notEstablished'][0]
    boundary['premises'][0]['quote']=evidence[0]['quote'];boundary[field]=value
    assert validate(claim,expression,result,evidence,consistent_premises=True)


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_partitioned_review_preserves_both_fields_and_applies_new_policy_only(enabled):
    claim,expression,record,evidence=inputs(settings=False)
    def add_excerpt(rows,request):rows[0]['premises'][0]['quote']='Method A retained quality at 66%.'
    checker,calls=checker_for(claim,expression,record,evidence,modify=add_excerpt,consistent=enabled)
    output=checker([claim],evidence)[0]
    assert output['status']==('passed' if enabled else 'failed') and len(calls)==1
    premise=output['partitionedScopeAudit']['notEstablished'][0]['premises'][0]
    assert premise=={'evidenceId':'own','path':['quote'],'quote':'Method A retained quality at 66%.'}
    assert ('both path and quote are returned' in calls[0]['prompt']) is enabled


@pytest.mark.parametrize('value',[None,True,False,0,1,2,'3',4])
def test_new_premise_policy_requires_exact_server_version(value):
    assert not consistent_premises_enabled({'scopeExpressionReviewContractVersion':value})
    assert consistent_premises_enabled({'scopeExpressionReviewContractVersion':3})


def test_facade_wires_new_checker_policy_and_keeps_legacy_runs_unchanged(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'scopeExpressionReviewContractVersion':False},start_async=False)
        assert facade._build_semantic_checker(run['runId'],Mock())._consistent_scope_premises() is True
        legacy=deepcopy(run);legacy.update(runId='old',idempotencyKey='old',scopeExpressionReviewContractVersion=2)
        repo.create_run(legacy);before=repo.require_run('old')
        assert facade._build_semantic_checker('old',Mock())._consistent_scope_premises() is False
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'scopeExpressionReviewContractVersion':2})
        assert repo.require_run('old')==before
    finally:facade.shutdown()
