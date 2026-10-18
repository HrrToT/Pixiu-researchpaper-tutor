from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audit_source_fields import resolve,enabled,GUIDANCE
from services.deep_research.factual_scope import validate_audit as validate_scope
from services.deep_research.comparison_reasoning import validate_audit as validate_comparison
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import make_evidence,verify_claims
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.facade import ResearchFacade
from test_deep_research_comparison_reasoning import inputs,audit


def source():
    text='The method uti-\nlizes a motion grid to estimate motion.'
    e=make_evidence({'workId':'paper','versionId':'v1','contentHash':'hash','accessLevel':'fulltext'},
        text,text,location={'page':2},obligation_ids=[])
    c={'claimId':'c','kind':'reported','text':'该方法用运动网格估计运动。','evidenceRefs':[e['evidenceId']]}
    a={'claimStrength':'bounded','evidenceStrength':'bounded','supported':True,
        'statementExcerpt':c['text'],'premises':[{'evidenceId':e['evidenceId'],'path':['quote']}]}
    return c,e,a


def test_raw_field_binding_avoids_typography_copy_without_changing_source_or_claim():
    c,e,a=source();before=deepcopy((c,e,a));v={'scopeAudit':a}
    assert not validate_scope(c,v,[e],source_field_bindings=True)
    assert validate_scope(c,v,[e])==['scope_premises_not_bound']
    copied=deepcopy(v);copied['scopeAudit']['premises']=[{'evidenceId':e['evidenceId'],
        'quote':e['quote'].replace('uti-\nlizes','utilizes')}]
    assert validate_scope(c,copied,[e],source_field_bindings=True)==['scope_premises_not_bound']
    assert before==(c,e,a)


@pytest.mark.parametrize('path',[['sourceTitle'],['sourceContext','truncated'],['sourceContext',0],
    ['sourceContext','fullDocument'],['quote','extra'],[],['quote',0],'quote',None])
def test_only_whitelisted_visible_string_fields_can_bind(path):
    c,e,a=source();assert resolve({'evidenceId':e['evidenceId'],'path':path},{e['evidenceId']:e}) is None


@pytest.mark.parametrize('change',['foreign','malformed_id','mixed_quote','unknown_key','empty','dictionary_context'])
def test_malformed_or_foreign_references_never_close_a_scope_audit(change):
    c,e,a=source();row=a['premises'][0]
    if change=='foreign':row['evidenceId']='other'
    elif change=='malformed_id':row['evidenceId']=[]
    elif change=='mixed_quote':row['quote']=e['quote']
    elif change=='unknown_key':row['content']='invented'
    elif change=='empty':e['quote']=' '
    else:e['sourceContext']={'before':'context'};row['path']=['sourceContext']
    assert validate_scope(c,{'scopeAudit':a},[e],source_field_bindings=True)==['scope_premises_not_bound']


def test_context_fields_resolve_only_existing_text_and_never_hidden_metadata():
    c,e,a=source();e['sourceContext']={'before':'Original before.','after':'Original after.','truncated':True}
    own={e['evidenceId']:e}
    assert resolve({'evidenceId':e['evidenceId'],'path':['sourceContext','before']},own)[1]=='Original before.'
    assert resolve({'evidenceId':e['evidenceId'],'path':['sourceContext','after']},own)[1]=='Original after.'
    assert resolve({'evidenceId':e['evidenceId'],'path':['sourceContext']},own) is None
    e['sourceContext']='Original bounded string.'
    assert resolve({'evidenceId':e['evidenceId'],'path':['sourceContext']},own)[1]==e['sourceContext']


def test_cross_source_audit_still_requires_both_original_identities():
    c,e=inputs();a=audit(e);a['premises']=[{'evidenceId':ev['evidenceId'],'path':['quote']} for ev in e]
    assert not validate_comparison(c,{'comparisonAudit':a},e,source_field_bindings=True)
    a['premises']=a['premises'][:1]
    assert validate_comparison(c,{'comparisonAudit':a},e,source_field_bindings=True)==['comparison_source_premise_missing']


@pytest.mark.parametrize('right_value',['Device Y','Device Z','Device X'])
def test_difference_values_and_same_source_rules_are_unchanged(right_value):
    c,e=inputs('Device Y');a=audit(e,'different')
    a['premises']=[{'evidenceId':ev['evidenceId'],'path':['quote']} for ev in e]
    a['differences']=[{'dimension':'hardware',
        'left':{'evidenceId':e[0]['evidenceId'],'path':['quote'],'value':'Device X'},
        'right':{'evidenceId':e[1]['evidenceId'],'path':['quote'],'value':right_value}}]
    errors=validate_comparison(c,{'comparisonAudit':a},e,source_field_bindings=True)
    assert bool(errors)==(right_value!='Device Y')
    a['differences'][0]['right']['evidenceId']=e[0]['evidenceId']
    assert validate_comparison(c,{'comparisonAudit':a},e,source_field_bindings=True)


@pytest.mark.parametrize('status',['passed','failed'])
def test_checker_restores_ids_binds_actual_visible_context_and_preserves_semantic_verdict(status):
    c,e,a=source();e['sourceContext']='HIDDEN_PREFIX'*1000+' VISIBLE_BEFORE '+e['quote']+' VISIBLE_AFTER '
    sent=[]
    def invoke(**kwargs):
        sent.append(kwargs)
        wire=deepcopy(a);wire['premises']=[{'evidenceId':'E1','path':['quote']}]
        return {'content':json.dumps([{'claimId':'c','status':status,'reason':'fixture','scopeAudit':wire}])}
    checker=BudgetedSemanticChecker(invoke,'r',factual_scope=True,audit_source_fields=True)
    result=verify_claims([c],[e],checker)
    assert bool(result['accepted'])==(status=='passed') and len(sent)==1
    assert GUIDANCE in sent[0]['prompt'] and 'HIDDEN_PREFIX'*100 not in sent[0]['prompt']
    assert sent[0]['extra_body']=={'max_tokens':4000,'temperature':0.0} and sent[0]['use_reserve'] is True
    no_verifier=verify_claims([c],[e]);assert not no_verifier['accepted']
    numeric={**c,'text':'报告999 FPS。'};check=Mock()
    assert verify_claims([numeric],[e],check)['rejected'][0]['reason']=='numeric_mismatch'
    check.assert_not_called()


def test_bounded_field_reference_does_not_establish_universal_or_exclusive_scope():
    c,e,a=source();a['claimStrength']='universal'
    assert validate_scope(c,{'scopeAudit':a},[e],source_field_bindings=True)==['scope_stronger_than_evidence']


@pytest.mark.parametrize('client_value',[0,1,True,None,'2',3])
def test_server_owns_frozen_field_binding_policy(tmp_path,client_value):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查',
            'auditSourceFieldsContractVersion':client_value,'deferStart':True},start_async=False)
        assert run['auditSourceFieldsContractVersion']==2 and enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'auditSourceFieldsContractVersion':client_value})
        assert facade._build_semantic_checker(run['runId'],Mock())._audit_source_fields() is True
    finally:facade.shutdown()
