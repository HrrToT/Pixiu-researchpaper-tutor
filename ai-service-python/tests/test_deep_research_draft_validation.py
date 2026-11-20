from copy import deepcopy
from unittest.mock import Mock
import json
import pytest

from services.deep_research.draft_validation import (
    enabled, materialize_claims, verification_inputs, reject_initial, protect_release)
from services.deep_research.graph import make_synthesize_node, make_verify_node


def drafts():
    valid={'claimId':'good','kind':'reported','text':'原文事实。','conditions':{},'evidenceRefs':['e'],'obligationIds':['o']}
    bad={'claimId':'bad','kind':'inference','text':'没有提供存储数据。','conditions':{},'evidenceRefs':['e'],'obligationIds':['o'],
         'scopeExpression':{'observedSettings':[{'subject':'方法','attribute':'硬件','value':'GPU A'}],'notEstablished':[]}}
    return {'sections':[{'title':'结果','claimIds':['good','bad']}],'claims':[valid,bad]}


def test_conflict_keeps_both_original_forms_and_never_selects_a_fact():
    report=drafts();before=deepcopy(report)
    value,scopes,audit=materialize_claims(report,4)
    assert value['claims'][1]==report['claims'][1]
    assert audit['rejected'][0]['originalClaim']==report['claims'][1]
    assert scopes==[] and report==before
    assert verification_inputs(value['claims'],audit)==[value['claims'][0]]
    # Even an over-permissive checker cannot approve the quarantined ID.
    result=reject_initial({'accepted':value['claims'],'rejected':[]},audit)
    assert [c['claimId'] for c in result['accepted']]==['good']
    assert result['rejected'][0]['reason']=='invalid_scope_expression'


@pytest.mark.parametrize('mutation',['duplicate','empty','not_object'])
def test_invalid_identities_still_fail_whole_draft(mutation):
    report=drafts()
    if mutation=='duplicate':report['claims'][1]['claimId']='good'
    elif mutation=='empty':report['claims'][1]['claimId']=''
    else:report['claims'][1]=None
    with pytest.raises(ValueError,match='identities'):materialize_claims(report,4)


def test_release_requires_exact_independently_checked_replacement():
    report,_,audit=materialize_claims(drafts(),4)
    original=report['claims'][1];fixed={**original,'text':'有来源支持的改写。'};fixed.pop('scopeExpression')
    result={'accepted':[report['claims'][0],fixed],'rejected':[]}
    assert [c['claimId'] for c in protect_release(result,audit,{})['accepted']]==['good']
    assert protect_release(result,audit,{'accepted':[fixed]})==result
    changed={**fixed,'text':'未经审核的新句子。'}
    assert not any(c['claimId']=='bad' for c in protect_release({'accepted':[changed]},audit,{'accepted':[fixed]})['accepted'])
    assert not protect_release({'accepted':[original]},audit,{'accepted':[original]})['accepted']


def make_store(record):
    store={'record':deepcopy(record)}
    def update(rid,fn,**kwargs):
        store['record']=fn(deepcopy(store['record']));return deepcopy(store['record'])
    return store,update


@pytest.mark.parametrize('policy',[None,0,True,'1',1])
def test_synthesis_preserves_legacy_rejection_and_only_server_version_isolates(policy):
    record={'scopeExpressionContractVersion':4,'question':'解释结果，200字以内',
            'state':{'outputKind':'claim_verification','evidence':[]}}
    if policy is not None:record['draftValidationContractVersion']=policy
    store,update=make_store(record);invoke=Mock(return_value={'content':json.dumps(drafts())})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    if type(policy) is int and policy==1:
        assert not result.get('error_code')
        state=store['record']['state']
        assert state['reportBody']['claims'][1]==drafts()['claims'][1]
        assert state['draftValidationAudit']['rejected'][0]['claimId']=='bad'
        assert invoke.call_count==1  # No structural retry/extra model call.
    else:
        assert result['error_code']=='invalid_synthesis_response'
        assert 'reportBody' not in store['record']['state']


@pytest.mark.parametrize('repair_passes',[False,True])
def test_actual_verification_repairs_only_through_existing_independent_checks(monkeypatch,repair_passes):
    report,_,audit=materialize_claims(drafts(),4)
    record={'draftValidationContractVersion':1,'scopeExpressionContractVersion':4,'question':'解释结果',
            'state':{'outputKind':'claim_verification','reportBody':report,'draftValidationAudit':audit,'evidence':[]},'budget':{}}
    store,update=make_store(record);checked=[]
    def verify(claims,evidence,semantic):
        checked.append(deepcopy(claims))
        assert drafts()['claims'][1] not in claims
        return {'accepted':[c for c in claims if c['claimId']=='good' or repair_passes],
                'rejected':[{'claimId':c['claimId'],'reason':'semantic_failed'} for c in claims if c['claimId']=='bad' and not repair_passes]}
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**k:{'status':'checked','gaps':[],'verdicts':[]})
    fixed={**report['claims'][1],'text':'原文只报告GPU A硬件。'};fixed.pop('scopeExpression')
    repair=Mock(return_value=[fixed]);monkeypatch.setattr('services.deep_research.repair.repair_rejected',repair)
    make_verify_node(verify,None,update,llm_invoke=Mock())({'run_id':'r'})
    state=store['record']['state'];accepted=state['verifiedReport']['verifiedClaims']
    assert len(checked)==2 and checked[0]==[report['claims'][0]] and checked[1]==[fixed]
    assert any(c['claimId']=='bad' for c in accepted)==repair_passes
    assert state['initialVerification']['rejected'][0]['reason']=='invalid_scope_expression'
    assert state['draftValidationAudit']==audit
    repair.assert_called_once()


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_server_owned_contract_is_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'比较论文',
                            'draftValidationContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['draftValidationContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'draftValidationContractVersion':replacement})
    finally:facade.shutdown()


def test_unmaterialized_scope_cannot_publish_even_with_missing_draft_audit():
    original=drafts()['claims'][1]
    assert not protect_release({'accepted':[original]}, {}, {'accepted':[original]})['accepted']
