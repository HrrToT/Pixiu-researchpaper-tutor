from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.claim_check import enabled, GUIDANCE, AUDIT_GUIDANCE
from services.deep_research.factual_template import build
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_verify_node
from services.deep_research.repair import repair_rejected


@pytest.mark.parametrize('value',[None,True,False,0,9,'1'])
def test_policy_requires_strict_version_and_claim_check_output(value):
    assert not enabled({'claimCheckContractVersion':value,'state':{'outputKind':'claim_verification'}})
    assert not enabled({'claimCheckContractVersion':1,'state':{'outputKind':'paper_comparison'}})
    assert enabled({'claimCheckContractVersion':1,'state':{'outputKind':'claim_verification'}})


def test_generation_and_compact_repair_preserve_guidance_without_changing_evidence():
    from test_deep_research_compact_source_repair import prepare
    args=('核查质量', 'claim_verification',300,2,[],[],{},'EVIDENCE','TABLES')
    record={'claimCheckContractVersion':1,'state':{'outputKind':'claim_verification'}}
    before=deepcopy(record)
    assert GUIDANCE not in build({},*args)
    assert GUIDANCE in build(record,*args)
    assert record==before
    old=prepare();new=prepare(claim_check=True)
    assert GUIDANCE not in old['prompt'] and GUIDANCE in new['prompt']
    assert old['originals']==new['originals'] and old['allowed']==new['allowed']


def test_result_packet_keeps_sibling_rows_and_available_provenance_without_foreign_attachment():
    from services.deep_research.claim_check import prioritize_results
    def row(key,quote,table=False,**changes):
        return {'evidenceId':key,'quote':quote,'sourceWorkId':'p','sourceVersionId':'v',
            'obligationIds':['o'],'verification':{'literal':'passed','semantic':'unchecked'},
            'location':{'table':'tab_a'} if table else {},**({'tableData':{'rows':[]}} if table else {}),**changes}
    rows=[row('intro','Summary repeats the author claim.'),row('base','Baseline 3D-GS values',True),
        row('ours','Ours values',True),row('note','For fair comparison, the baseline was re-trained.'),
        row('foreign','re-trained baseline',sourceWorkId='other'),
        row('version','re-trained baseline',sourceVersionId='other'),
        row('unchecked','re-trained baseline',verification={'literal':'failed'}),
        row('other_table','Additional results',True,location={'table':'tab_b'})]
    before=deepcopy(rows);ordered,bundles=prioritize_results(rows,[],'核查与3DGS比较')
    assert [r['evidenceId'] for r in ordered[:3]]==['base','ours','note']
    assert bundles[0]['evidenceIds']==['base','ours','note'] and rows==before
    assert all(r['verification'].get('semantic')!='passed' for r in ordered)
    assert set(r['evidenceId'] for r in rows)==set(r['evidenceId'] for r in ordered)


def test_no_table_or_unknown_identity_preserves_original_selection():
    from services.deep_research.claim_check import prioritize_results
    rows=[{'evidenceId':'e','quote':'Only summary is available.'}];bundles=[{'evidenceIds':['e']}]
    assert prioritize_results(rows,bundles,'核查')==(rows,bundles)
    rows[0].update(tableData={'rows':[]},verification={'literal':'passed'})
    assert prioritize_results(rows,bundles,'核查')==(rows,bundles)


def test_inference_policy_removes_blanket_difference_ban_only_for_new_claim_checks():
    from services.deep_research.claim_check import INFERENCE_GUIDANCE
    args=('核查质量','claim_verification',300,2,[],[],{},'EVIDENCE','TABLES')
    record={'state':{'outputKind':'claim_verification'}}
    for version in (None,1,2):
        old=build({**record,'claimCheckContractVersion':version},*args)
        assert 'No unknown values, inferred differences,' in old
        assert INFERENCE_GUIDANCE not in old
    current=build({**record,'claimCheckContractVersion':3},*args)
    assert 'No unknown values, inferred differences,' not in current
    assert 'Do not present inferred differences as directly reported values.' in current
    assert INFERENCE_GUIDANCE in current
    # Guidance is not a numerical waiver: a fabricated reported difference must
    # still fail ordinary verification independently of any prompt policy.
    from services.deep_research.verification import verify_claims
    result=verify_claims([{'claimId':'c','kind':'reported','text':'差值为0.3。','evidenceRefs':['e']}],
        [{'evidenceId':'e','quote':'Values are 27.13 and 27.21.','accessLevel':'fulltext'}])
    assert not result['accepted']


def test_audit_guidance_cannot_promote_invalid_response_or_modify_claims():
    from test_deep_research_request_coverage import QUESTION,PLAN,CLAIMS,EVIDENCE
    before=deepcopy((PLAN,CLAIMS,EVIDENCE));prompts=[]
    def invoke(*args,**kwargs):
        prompts.append(args[2]);return {'content':'[]'}
    old=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,request_contract=2)
    new=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,request_contract=2,claim_check=True)
    assert AUDIT_GUIDANCE not in prompts[0] and AUDIT_GUIDANCE in prompts[1]
    assert old['gaps'] and new['gaps'] and new['status']=='invalid_response'
    assert (PLAN,CLAIMS,EVIDENCE)==before


def test_repair_resume_identity_includes_quality_policy_without_reapproving_content():
    c={'claimId':'c','kind':'reported','text':'old','evidenceRefs':['e']}
    invoke=Mock(return_value={'content':json.dumps([{**c,'text':'revised'}])});states=[]
    args=({'claims':[c]},{'accepted':[],'rejected':[{'claimId':'c'}]},
          [{'evidenceId':'e','quote':'provided observation'}],'核查',invoke,json.loads)
    result=repair_rejected(*args,claim_check=True,checkpoint=states.append)
    assert len(result)==1 and result[0]['kind']=='reported'
    assert result[0].get('verification') not in ('verified','accepted')
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(*args,claim_check=True,batch_state=saved)==result
    invoke.assert_not_called()
    with pytest.raises(Exception,match='修订计划'):
        repair_rejected(*args,batch_state=saved)
    invoke.assert_not_called()


@pytest.mark.parametrize('active',[True,False,4,5,6,7,8])
def test_initial_audit_repair_and_second_audit_receive_same_frozen_policy(active,monkeypatch):
    from test_deep_research_request_dimensions import plan
    c={'claimId':'c','kind':'inference','text':'old','evidenceRefs':['e']}
    record={'question':'核查质量','state':{'outputKind':'claim_verification',
        'reportBody':{'claims':[c]},'evidence':[],'plan':plan('核查质量')}}
    if active:record['claimCheckContractVersion']=active if type(active) is int else 1
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    audits=[];repairs=[]
    def audit(*args,**kwargs):
        audits.append(kwargs);return {'status':'checked','gaps':[]}
    def repair(*args,**kwargs):
        repairs.append(kwargs);return [{**c,'text':'revised'}]
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',audit)
    monkeypatch.setattr('services.deep_research.repair.repair_rejected',repair)
    verify=Mock(side_effect=[{'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},
        {'accepted':[{**c,'text':'revised'}],'rejected':[]}])
    make_verify_node(verify,None,update,llm_invoke=lambda *a,**kw:{'content':'[]'})({'run_id':'r'})
    assert len(audits)==2 and len(repairs)==1 and verify.call_count==2
    assert all(kw.get('claim_check',False) is bool(active) for kw in audits)
    assert all(kw.get('claim_check',False)==active for kw in repairs)
    if type(active) is int:assert type(repairs[0]['claim_check']) is int
    if active in (5,6,7,8):assert repairs[0]['required_scope_ids']==[]


@pytest.mark.parametrize('replacement',[None,True,0,'1',9])
def test_new_policy_is_server_owned_immutable_and_absent_from_legacy(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'claimCheckContractVersion':replacement},start_async=False)
        assert type(run['claimCheckContractVersion']) is int and run['claimCheckContractVersion']==8
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'claimCheckContractVersion':replacement})
        legacy=deepcopy(run);legacy.update(runId='legacy',idempotencyKey='legacy');legacy.pop('claimCheckContractVersion')
        repo.create_run(legacy);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'继续','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
    finally:facade.shutdown()


def test_new_assessment_policy_is_shared_by_generation_and_repair_without_changing_evidence():
    from services.deep_research.claim_check import ASSESSMENT_GUIDANCE,INFERENCE_GUIDANCE
    from test_deep_research_compact_source_repair import prepare
    args=('核查质量','claim_verification',300,2,[],[],{},'EVIDENCE','TABLES')
    record={'claimCheckContractVersion':4,'state':{'outputKind':'claim_verification'}}
    current=build(record,*args);old=build({**record,'claimCheckContractVersion':3},*args)
    repaired=prepare(claim_check=4);legacy=prepare(claim_check=True)
    assert ASSESSMENT_GUIDANCE in current and ASSESSMENT_GUIDANCE in repaired['prompt']
    assert GUIDANCE not in current and GUIDANCE not in repaired['prompt']
    assert ASSESSMENT_GUIDANCE not in old and ASSESSMENT_GUIDANCE not in legacy['prompt']
    assert INFERENCE_GUIDANCE in old
    assert repaired['allowed']==legacy['allowed'] and repaired['originals']==legacy['originals']
    assert 'not "X was not tested"' in ASSESSMENT_GUIDANCE


def test_new_repair_policy_cannot_reuse_legacy_batch_response():
    from services.deep_research.contracts import DeepResearchError
    c={'claimId':'c','kind':'reported','text':'old','evidenceRefs':['e']}
    report={'claims':[c]};verification={'accepted':[],'rejected':[{'claimId':'c'}]}
    evidence=[{'evidenceId':'e','quote':'provided observation'}]
    invoke=Mock(return_value={'content':'[]'});states=[]
    args=(report,verification,evidence,'核查质量，300字以内',invoke,json.loads)
    result=repair_rejected(*args,claim_check=4,checkpoint=states.append)
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(*args,claim_check=4,batch_state=saved)==result
    with pytest.raises(DeepResearchError):repair_rejected(*args,claim_check=True,batch_state=saved)
    invoke.assert_not_called()


@pytest.mark.parametrize('value',[1,2,3,9,'4',None])
def test_bad_repair_policy_cannot_silently_select_new_guidance(value):
    c={'claimId':'c','kind':'reported','text':'old','evidenceRefs':['e']};invoke=Mock()
    with pytest.raises(ValueError,match='Invalid claim check policy'):
        repair_rejected({'claims':[c]},{'accepted':[],'rejected':[{'claimId':'c'}]},[],
            '核查',invoke,json.loads,claim_check=value)
    invoke.assert_not_called()
