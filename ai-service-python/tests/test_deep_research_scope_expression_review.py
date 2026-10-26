from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.scope_expression import materialize
from services.deep_research.scope_expression_review import context_for_record,validate
from services.deep_research.tools import BudgetedSemanticChecker


def fixture():
    raw={'claimId':'c','kind':'inference','text':'','conditions':{},'evidenceRefs':['real'],
        'scopeExpression':{'observedSettings':[{'subject':'A','attribute':'setting','value':'66%'}],
                           'notEstablished':['所有设置均保持相同质量']}}
    row,audit=materialize(raw)
    record={'scopeExpressionReviewContractVersion':1,'state':{'synthesisScopeExpressionAudit':[audit]}}
    evidence=[{'evidenceId':'real','quote':'We observed comparable quality at setting 66%.',
               'sourceContext':'At setting 70% quality declined.','verification':{'literal':'passed'}}]
    return row,raw['scopeExpression'],record,evidence


def verdict(expression,evidence_id='real'):
    premise={'evidenceId':evidence_id,'path':['quote']}
    return {'claimId':'c','status':'passed','scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded',
        'supported':True,'statementPath':['text'],'premises':[premise]},'scopeExpressionAudit':{
        'observedSettings':[{'index':0,'setting':deepcopy(expression['observedSettings'][0]),
            'status':'supported','premises':[premise]}],
        'notEstablished':[{'index':0,'proposition':expression['notEstablished'][0],'relation':'not_entailed',
            'quantification':'explicit','isNegation':False,'authorOmission':False,
            'reason':'One setting observation and a counterexample do not entail the universal statement.',
            'premises':[premise]}]}}


def test_context_requires_exact_current_text_and_a_valid_equivalent_expression():
    row,expression,record,evidence=fixture();before=deepcopy(record)
    assert context_for_record(record,[row])=={'c':expression} and record==before
    assert context_for_record(record,[{**row,'text':'Changed actual assertion'}])=={}
    assert context_for_record(record,[{**row,'kind':'reported'}])=={}
    bad=deepcopy(record);bad['state']['synthesisScopeExpressionAudit'][0]['expression']['notEstablished']=['Different claim']
    assert context_for_record(bad,[row])=={}
    for marker in (None,True,'1',0):assert context_for_record({**record,'scopeExpressionReviewContractVersion':marker},[row])=={}


def test_repair_context_overrides_stale_initial_text_only_by_an_exact_match():
    row,expression,record,evidence=fixture();audit=record['state']['synthesisScopeExpressionAudit'][0]
    record['state']['synthesisScopeExpressionAudit']=[{**audit,'renderedText':'stale'}]
    record['state']['repairBatchState']={'scopeExpressionAudit':{'0':[audit]}}
    assert context_for_record(record,[row])=={'c':expression}


@pytest.mark.parametrize('field,value',[
    ('relation','entailed'),('relation','undetermined'),('quantification','ambiguous'),
    ('isNegation',True),('authorOmission',True),('reason',''),('proposition','Different proposition')])
def test_a_passed_verdict_never_bypasses_entailment_quantifier_or_author_omission_checks(field,value):
    row,expression,record,evidence=fixture();result=verdict(expression)
    result['scopeExpressionAudit']['notEstablished'][0][field]=value
    assert validate(row,expression,result,evidence)==['scope_boundary_entailment_unresolved']


@pytest.mark.parametrize('mutation', ['missing','foreign','invented','wrong_setting','boolean_index','missing_item'])
def test_missing_audits_unbound_sources_and_changed_setting_bindings_still_fail(mutation):
    row,expression,record,evidence=fixture();result=verdict(expression)
    if mutation=='missing':result.pop('scopeExpressionAudit')
    elif mutation=='foreign':result['scopeExpressionAudit']['observedSettings'][0]['premises']=[{'evidenceId':'foreign','path':['quote']}]
    elif mutation=='invented':result['scopeExpressionAudit']['observedSettings'][0]['premises']=[{'evidenceId':'real','quote':'All settings work.'}]
    elif mutation=='wrong_setting':result['scopeExpressionAudit']['observedSettings'][0]['setting']['value']='<=70%'
    elif mutation=='boolean_index':result['scopeExpressionAudit']['observedSettings'][0]['index']=False
    else:result['scopeExpressionAudit']['notEstablished']=[]
    assert validate(row,expression,result,evidence)


def test_checker_supplies_equivalent_operator_context_restores_own_aliases_and_requires_both_audits():
    row,expression,record,evidence=fixture();sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);return {'content':json.dumps([verdict(expression,'E1')]),'finishReason':'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',factual_scope=True,complete_factual_scope=True,
        audit_source_fields=True,audit_target_fields=True,
        scope_expression_context=lambda targets:context_for_record(record,targets))
    result=checker([row],evidence)
    assert result[0]['status']=='passed' and result[0]['scopeExpressionAudit']['observedSettings'][0]['premises'][0]['evidenceId']=='real'
    assert 'Structured scope-expression review' in sent[0]['prompt'] and 'does NOT require an author-written disclaimer' in sent[0]['prompt']
    assert evidence[0]['quote'] in sent[0]['prompt'] and 'Scope-strength audit' in sent[0]['prompt']
    def missing(**kwargs):
        v=verdict(expression,'E1');v.pop('scopeExpressionAudit');return {'content':json.dumps([v]),'finishReason':'stop'}
    checker._invoke=missing
    assert checker.check_revisions([row],evidence,[])[0]['status']=='failed'


def test_checker_does_not_upgrade_a_failed_semantic_verdict_or_change_legacy_prompt():
    row,expression,record,evidence=fixture();sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);v=verdict(expression,'E1');v.update(status='failed',reason='Source actually proves the broader theorem')
        return {'content':json.dumps([v]),'finishReason':'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',scope_expression_context=lambda targets:context_for_record(record,targets))
    result=checker([row],evidence)
    assert result[0]['status']=='failed' and result[0]['reason']=='Source actually proves the broader theorem'
    BudgetedSemanticChecker(invoke,'r')([row],evidence)
    assert 'Structured scope-expression review' not in sent[-1]['prompt']


def test_alias_restoration_is_explicit_and_never_rewrites_quote_strings_or_legacy_fields():
    from services.deep_research.verification_aliases import restore_verdict_evidence
    row,expression,record,evidence=fixture();v=json.loads(json.dumps(verdict(expression,'E1')))
    v['scopeExpressionAudit']['notEstablished'][0]['reason']='E1 here is unchanged prose.'
    before=deepcopy(v)
    legacy=restore_verdict_evidence(v,{'E1':'real'})
    assert legacy['scopeExpressionAudit']['observedSettings'][0]['premises'][0]['evidenceId']=='E1'
    result=restore_verdict_evidence(v,{'E1':'real'},scope_expression=True)
    assert result['scopeExpressionAudit']['observedSettings'][0]['premises'][0]['evidenceId']=='real'
    assert result['scopeExpressionAudit']['notEstablished'][0]['reason']=='E1 here is unchanged prose.'
    assert v==before


@pytest.mark.parametrize('replacement',[None,0,True,'1',1,3])
def test_policy_is_server_owned_immutable_and_facade_only_supplies_matching_new_context(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    from test_deep_research_quantified_scope import quantified
    raw=quantified();row,audit=materialize(raw,2)
    from services.deep_research.scope_expression import review_expression
    expression=review_expression(raw['scopeExpression'],2)
    record={'state':{'synthesisScopeExpressionAudit':[audit]}}
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'scopeExpressionReviewContractVersion':replacement},start_async=False)
        assert run['scopeExpressionReviewContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'scopeExpressionReviewContractVersion':replacement})
        run=repo.update_run(run['runId'],lambda r:{**r,'state':record['state']})
        checker=facade._build_semantic_checker(run['runId'],Mock())
        assert checker._scope_expression_context([row])=={'c':expression}
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('scopeExpressionReviewContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        assert facade._build_semantic_checker('old',Mock())._scope_expression_context([row])=={}
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()
