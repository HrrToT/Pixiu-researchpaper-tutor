from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.reporting_ownership import targets,validate,enabled
from services.deep_research.tools import BudgetedSemanticChecker


def evidence():
    return [
        {'evidenceId':'g-hw','sourceWorkId':'gof','accessLevel':'fulltext','sourceVersionId':'gof-v1','sourceTitle':'Gaussian Opacity Fields: Surface Reconstruction','quote':'We train on NVIDIA A100 GPU.'},
        {'evidenceId':'g-own','sourceWorkId':'gof','accessLevel':'fulltext','sourceVersionId':'gof-v1','sourceTitle':'Gaussian Opacity Fields: Surface Reconstruction','quote':'Ours mean Chamfer 0.74 mm; training time 30 min.'},
        {'evidenceId':'p-table','sourceWorkId':'pgsr','accessLevel':'fulltext','sourceVersionId':'pgsr-v1','sourceTitle':'PGSR: Planar-based Gaussian Splatting','quote':'PGSR mean 0.49, time 1.0h; GOF mean 0.74, time 2h. Average GOF PSNR 27.78, SSIM 0.835, LPIPS 0.196.'}]


def claim(text,refs=None):return {'claimId':'c','kind':'reported','text':text,'conditions':{},'evidenceRefs':refs or ['g-hw','p-table']}


def audit(ids):return {'reportingOwnershipAudit':[{'index':0,'supported':True,'premises':[{'evidenceId':eid,'path':['quote']} for eid in ids]}]}


def test_reporter_identity_is_distinct_from_a_method_row_in_another_paper():
    rows=evidence();c=claim('GOF 报告平均 Chamfer 0.74 mm，耗时2小时（A100）。')
    assert targets(c,rows)[0]['reportingWorkIds']==['gof']
    assert validate(c,audit(['p-table']),rows)==['reporting_paper_mismatch']
    assert validate(c,audit(['g-hw']),rows)==['reporting_numbers_not_in_own_premises']
    assert validate(c,{},rows)==['reporting_ownership_audit_missing']
    # A correctly attributed comparator stays a valid reporting relationship;
    # this structure still grants no semantic approval for values/conditions.
    comparator=claim('PGSR reports GOF mean 0.74 and time 2h.',['p-table'])
    assert len(targets(comparator,rows))==1
    assert validate(comparator,audit(['p-table']),rows)==[]
    assert validate(comparator,audit(['g-own']),rows)==['reporting_premise_not_bound']


def test_own_paper_values_can_pass_identity_only_when_all_requested_numbers_are_bound():
    c=claim('GOF 报告 mean Chamfer 0.74 mm，耗时30 min。',['g-own'])
    assert validate(c,audit(['g-own']),evidence())==[]
    assert validate(c,audit(['g-hw']),evidence())==['reporting_premise_not_bound']
    both=claim('PGSR 报告平均0.49；GOF报告平均0.74。',['p-table','g-own'])
    assert len(targets(both,evidence()))==2
    wrong=audit(['p-table']);wrong['reportingOwnershipAudit'].append({'index':1,'supported':True,'premises':[{'evidenceId':'p-table','path':['quote']}]})
    assert validate(both,wrong,evidence())==['reporting_paper_mismatch']
    wrong['reportingOwnershipAudit'][1]['premises'][0]['evidenceId']='g-own'
    assert validate(both,wrong,evidence())==[]


@pytest.mark.parametrize('mutation',['negative','foreign','metadata','boolean_index','missing_row','extra_field'])
def test_source_audit_cannot_be_populated_with_unresolved_or_non_source_bindings(mutation):
    c=claim('GOF reports mean 0.74.',['g-own']);v=audit(['g-own'])
    if mutation=='negative':v['reportingOwnershipAudit'][0]['supported']=False
    elif mutation=='foreign':v['reportingOwnershipAudit'][0]['premises'][0]['evidenceId']='foreign'
    elif mutation=='metadata':v['reportingOwnershipAudit'][0]['premises'][0]['path']=['sourceTitle']
    elif mutation=='boolean_index':v['reportingOwnershipAudit'][0]['index']=False
    elif mutation=='missing_row':v['reportingOwnershipAudit']=[]
    else:v['reportingOwnershipAudit'][0]['approval']='passed'
    before=deepcopy((c,v));assert validate(c,v,evidence()) and (c,v)==before


def test_unknown_or_ambiguous_names_do_not_select_an_arbitrary_reporting_paper():
    rows=evidence()+[{**evidence()[1],'sourceWorkId':'different-work'}]
    assert validate(claim('GOF报告0.74。',['g-own']),audit(['g-own']),rows)==['reporting_identity_ambiguous']
    assert targets(claim('若优先几何精度，建议考虑PGSR。'),rows)==[]
    assert targets(claim('GOF uses a Gaussian representation.'),rows)==[]
    assert not enabled({'reportingOwnershipContractVersion':True})


@pytest.mark.parametrize('policy',[False,True])
def test_actual_checker_cannot_accept_misattribution_even_with_a_positive_semantic_response(policy):
    rows=evidence();c=claim('GOF 报告平均0.74，耗时2小时。');sent=[]
    def invoke(**kw):
        sent.append(kw)
        response={'claimId':'c','status':'passed','reason':'Fixture whole-claim positive'}
        if policy:response.update(audit(['E2']))
        return {'content':json.dumps([response])}
    checker=BudgetedSemanticChecker(invoke,'r',reporting_ownership=policy)
    result=checker([c],rows)
    assert result[0]['status']==('failed' if policy else 'passed')
    assert ('reporting_paper_mismatch' in result[0]['reason']) is policy
    assert ('reportingOwnershipAudit' in sent[0]['prompt']) is policy


def test_strict_single_decision_envelope_allows_new_audit_only_when_enabled():
    from services.deep_research.factual_decision import decode
    from services.deep_research.contracts import DeepResearchError
    v={'claimId':'c','reason':'Fixture positive','scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded','supported':True,'statementPath':['text'],'premises':[{'evidenceId':'E1','path':['quote']}]},**audit(['E1'])}
    with pytest.raises(DeepResearchError):decode([v])
    assert decode([v],reporting_ownership=True)[0]['status']=='passed'
    v['scopeAudit']['supported']=False
    assert decode([v],reporting_ownership=True)[0]['status']=='failed'

@pytest.mark.parametrize('supported',[False,True])
def test_strict_production_decision_restores_new_aliases_without_overriding_semantic_failure(supported):
    c=claim('GOF报告平均0.74。',['g-own']);sent=[]
    def invoke(**kw):
        sent.append(kw)
        return {'content':json.dumps([{'claimId':'c','reason':'Fixture independent semantic decision',
            'scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded','supported':supported,
                'statementPath':['text'],'premises':[{'evidenceId':'E1','path':['quote']}]},**audit(['E1'])}])}
    checker=BudgetedSemanticChecker(invoke,'r',reporting_ownership=True,single_factual_decision=True,
        factual_scope=True,complete_factual_scope=True,audit_source_fields=True,audit_target_fields=True)
    result=checker([c],evidence())
    assert result[0]['status']==('passed' if supported else 'failed')
    assert result[0]['reportingOwnershipAudit'][0]['premises'][0]['evidenceId']=='g-own'
    assert len(sent)==1


def test_unrelated_comparison_numbers_do_not_become_the_reporters_own_values():
    c=claim('GOF reports 30 min，比PGSR 1.0h更快。',['g-own','p-table'])
    required=targets(c,evidence());assert len(required)==1 and '1.0' not in required[0]['statementExcerpt']
    assert validate(c,audit(['g-own']),evidence())==[]
    # This does not approve the speed claim; independent comparison checks remain.


@pytest.mark.parametrize('client_value',[None,True,0,2])
def test_policy_is_server_owned_typed_immutable_and_not_added_to_legacy_runs(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较',
            'deferStart':True,'reportingOwnershipContractVersion':client_value},start_async=False)
        assert enabled(record) and record['reportingOwnershipContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'reportingOwnershipContractVersion':client_value})
        old=deepcopy(record);old.update(runId='legacy',idempotencyKey='old');old.pop('reportingOwnershipContractVersion')
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'比较','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before and not enabled(before)
    finally:facade.shutdown()


def test_legacy_unknown_audit_fields_are_not_reinterpreted_without_policy():
    from services.deep_research.verification_aliases import restore_verdict_evidence
    raw=audit(['E1']);before=deepcopy(raw)
    assert restore_verdict_evidence(raw,{'E1':'g-own'})==raw==before
    assert restore_verdict_evidence(raw,{'E1':'g-own'},reporting_ownership=True)['reportingOwnershipAudit'][0]['premises'][0]['evidenceId']=='g-own'


def test_user_notes_cannot_supply_paper_self_report_measurements():
    rows=evidence();note={**rows[1],'accessLevel':'user_note'}
    assert validate(claim('GOF reports mean 0.74.',['g-own']),audit(['g-own']),[rows[0],note,rows[2]])==['reporting_source_not_original_text']
    other_note={**rows[1],'sourceWorkId':'my-note','accessLevel':'user_note'}
    assert targets(claim('GOF reports mean 0.74.'),[*rows,other_note])[0]['reportingWorkIds']==['gof']


@pytest.mark.parametrize('connector',['因此','所以','therefore','thus'])
def test_computed_conclusion_is_not_relabelled_as_a_paper_report(connector):
    rows=evidence();rows[1]['quote']='Our reported storage is 10 MB.'
    c={**claim('GOF报告存储10 MB，'+connector+'相对给定基线20 MB可计算为减少50%。',['g-own']),'kind':'inference'}
    required=targets(c,rows)
    assert len(required)==1 and '50' not in required[0]['statementExcerpt'] and '20' not in required[0]['statementExcerpt']
    assert validate(c,audit(['g-own']),rows)==[]
    # Only the reporting prerequisite passes. The baseline, arithmetic and
    # resulting inference still need the ordinary independent review.


def test_english_reporting_verb_may_touch_chinese_prose_without_losing_identity():
    required=targets(claim('GOF reports平均0.74。'),evidence())
    assert len(required)==1 and required[0]['reportingWorkIds']==['gof']
