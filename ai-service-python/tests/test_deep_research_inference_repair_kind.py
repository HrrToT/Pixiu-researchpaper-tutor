from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.claim_check import inference_repair_ids
from services.deep_research.verification import verify_claims
from services.deep_research.contracts import DeepResearchError


def packet(policy=6):
    c={'claimId':'c','kind':'reported','text':'作者报告质量接近。','conditions':{},'evidenceRefs':['e'],'obligationIds':['o']}
    report={'claims':[c]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    ev=[{'evidenceId':'e','quote':'作者报告质量接近。','accessLevel':'fulltext','verification':{'literal':'passed'}}]
    p=_prepare_repair(report,checks,ev,'核查该结论，200字以内',claim_check=policy)
    row={**c,'kind':'inference','text':'这些已报告结果支持质量大致接近，但不能等同无损。','evidenceRefs':['E1'],
        'draftingBasis':{'premiseStatus':'established','scopeDecision':'bounded_inference','observations':[{'evidenceId':'E1','quote':'作者报告质量接近。'}],'unresolved':''}}
    return report,checks,ev,p,row


def test_qualified_judgement_can_change_kind_but_cannot_inherit_semantic_approval():
    report,checks,ev,p,row=packet();before=deepcopy((report,checks,ev));audit=[]
    out=_parse_repair_response(p,{'content':json.dumps([row])},json.loads,drafting_audit=audit)
    assert len(out)==1 and out[0]['kind']=='inference' and out[0]['claimId']=='c'
    assert out[0]['evidenceRefs']==['e'] and out[0]['obligationIds']==['o']
    assert audit[0]['kindTransition']=={'from':'reported','to':'inference','reason':'answer_incomplete','verification':'unchecked'}
    verify=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'not established by supplied facts'}])
    result=verify_claims(out,ev,verify,table_references_version=2)
    assert not result['accepted'] and result['rejected'][0]['reason']=='semantic_unresolved'
    verify.assert_called_once();assert (report,checks,ev)==before


@pytest.mark.parametrize('mode',['missing_intent','wrong_intent','tag_only','foreign_evidence','other_kind'])
def test_transition_cannot_be_used_to_relabel_unchanged_or_unsupported_inputs(mode):
    report,checks,ev,p,row=packet()
    if mode=='missing_intent':row.pop('draftingBasis')
    elif mode=='wrong_intent':row['draftingBasis']['scopeDecision']='reported_case'
    elif mode=='tag_only':row['text']=report['claims'][0]['text']
    elif mode=='foreign_evidence':row['evidenceRefs']=['foreign']
    elif mode=='other_kind':row['kind']='proposal'
    assert _parse_repair_response(p,{'content':json.dumps([row])},json.loads)==[]


@pytest.mark.parametrize('policy',[False,True,4,5,'6',None])
def test_old_policy_keeps_kind_frozen(policy):
    report,checks,ev,p,row=packet(policy)
    assert 'reportedInferenceRepairIds' not in p
    assert _parse_repair_response(p,{'content':json.dumps([row])},json.loads)==[]


@pytest.mark.parametrize('mode',['not_incomplete','proposal','design','inference_to_reported'])
def test_transition_scope_excludes_other_reasons_and_experimental_roles(mode):
    report,checks,ev,p,row=packet()
    if mode=='not_incomplete':checks['rejected'][0]['reason']='semantic_unresolved'
    elif mode=='proposal':report['claims'][0]['kind']='proposal'
    elif mode=='design':report['claims'][0]['designContractVersion']=2
    elif mode=='inference_to_reported':report['claims'][0]['kind']='inference'
    assert inference_repair_ids(report,checks,6)==[]


def test_additional_fixed_coverage_check_can_permit_correct_type_and_metadata_is_not_truth():
    report,checks,ev,p,row=packet();checks['rejected'][0]={'claimId':'c','reason':'semantic_unresolved',
        'additionalChecks':[{'reason':'answer_incomplete'}]}
    assert inference_repair_ids(report,checks,6)==['c']
    checks['rejected'][0]['additionalChecks']=None
    assert inference_repair_ids(report,checks,6)==[]


def test_new_type_policy_has_distinct_cache_and_resumes_without_resending():
    report,checks,ev,p,row=packet();states=[];invoke=Mock(return_value={'content':json.dumps([row])})
    args=(report,checks,ev,'核查该结论，200字以内',invoke,json.loads)
    out=repair_rejected(*args,claim_check=6,checkpoint=states.append)
    assert out[0]['kind']=='inference' and states[-1]['factualDraftingAudit']['0'][0]['kindTransition']['verification']=='unchecked'
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(*args,claim_check=6,batch_state=saved)==out
    with pytest.raises(DeepResearchError):repair_rejected(*args,claim_check=5,batch_state=saved)
    invoke.assert_not_called()


def test_new_policy_can_correct_semantically_unresolved_report_without_inventing_support():
    report,checks,ev,p,row=packet();checks['rejected'][0]['reason']='semantic_unresolved'
    new=_prepare_repair(report,checks,ev,'核查该结论',claim_check=8);old=_prepare_repair(report,checks,ev,'核查该结论',claim_check=7)
    assert new['reportedInferenceRepairIds']==['c'] and 'reportedInferenceRepairIds' not in old
    audit=[];out=_parse_repair_response(new,{'content':json.dumps([row])},json.loads,drafting_audit=audit)
    assert out[0]['kind']=='inference' and audit[0]['kindTransition']['reason']=='semantic_unresolved'
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'no approval supplied'}])
    assert not verify_claims(out,ev,checker)['accepted']
    assert 'semantic_unresolved with YOUR' in new['prompt']


@pytest.mark.parametrize('reason',['numeric_mismatch','unverified_quotation','table_cell_mismatch'])
def test_new_policy_does_not_type_away_a_hard_source_or_numeric_failure(reason):
    report,checks,ev,p,row=packet();checks['rejected'][0]={'claimId':'c','reason':reason,
        'additionalChecks':[{'reason':'answer_incomplete'}]}
    assert inference_repair_ids(report,checks,8)==[]
    assert inference_repair_ids(report,checks,7)==['c']  # Legacy policy preserved.
