"""Invalid review bindings are corrected once, never treated as answer facts."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.coverage_binding_correction import KEY,GUIDANCE,correct,enabled
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.coverage_repair import prepare_coverage_repair
from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
from test_deep_research_coverage_instructions import inputs

Q='如何把输入视图转换为深度图？'
PLAN=[{'obligations':[{'obligationId':'o','question':Q}]}]
CLAIMS=[{'claimId':'c','kind':'reported','text':'计算法线和距离并转换为深度图。','conditions':{},'obligationIds':['o']}]


def links(output='深度图'):
    return [{'input':{'request':'输入视图'},'operation':{'id':'c','field':'text','excerpt':'计算法线和距离并转换为深度图'},'output':{'request':output}}]


def policy():
    return {'state':{'outputKind':'claim_verification'},KEY:1,'requestCoverageContractVersion':5,'coverageInstructionsContractVersion':1,
        'coverageDiagnosticsContractVersion':4,'coverageRepairRoutingContractVersion':1,'coverageLimitContractVersion':1}


def run(mode='valid',*,activate=True,initial='unbound',reasoned=False):
    sent=[];before=deepcopy((PLAN,CLAIMS))
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append((node,prompt,options,kwargs))
        if prompt.startswith(GUIDANCE):
            data=json.loads(prompt.split('Frozen review inputs:\n',1)[1]);target=data['targets'][0]
            if mode=='budget':raise BudgetExhaustedError('modelCalls',1,1)
            if mode=='unknown':raise DeepResearchError('call_unknown','Observe original call')
            if mode=='capacity':raise AssertionError('Capacity rejection must precede dispatch')
            row={'obligationId':target['obligationId'],'checkId':target['checkId'],'status':'covered','processLinks':links(),'reason':'Actual operation connects the stated input and output.'}
            if mode=='unresolved':row.update(status='unresolved',processLinks=[],reason='Unable to resolve the review binding, no content deficiency established.')
            elif mode=='partial':row.update(status='partial',processLinks=[],reason='The requested operation is still missing.')
            elif mode=='foreign':row['processLinks'][0]['operation']['id']='foreign'
            elif mode=='unbound':row['processLinks']=links('生成深度')
            elif mode=='extra':row['text']='must never change answer text'
            elif mode=='wrong_id':row['checkId']='foreign'
            elif mode=='overlap':row['processLinks'][0]['input']={'request':Q};row['processLinks'][0]['output']={'request':Q}
            elif mode=='purpose':row['processLinks'][0]['operation']['excerpt']='用于生成深度图'
            elif mode=='malformed':return {'content':'not json'}
            elif mode=='missing':return {'content':'[]'}
            return {'content':json.dumps([row]),'finishReason':'length' if mode=='truncated' else 'stop'}
        value=inputs(prompt);rows=[]
        for obligation in value['requirements']:
            rows.append({'obligationId':obligation['obligationId'],'checks':[{'checkId':c['checkId'],'status':'partial' if initial=='partial' and obligation['obligationId']=='o' else 'covered','bindings':[{'claimId':'c','field':'text'}],'reason':'Initial semantic coverage judgement.','processLinks':links('生成深度' if obligation['obligationId']=='o' and initial=='unbound' else '深度图')} for c in obligation['checks']]})
        return {'content':json.dumps(rows)}
    result=audit_final_answer('r',Q,PLAN,CLAIMS,[],invoke,json.loads,request_contract=5,diagnostics=True,
        shared_decision_inputs=True,consolidated_instructions=True,literal_limits=True,correct_process_bindings=activate,reasoned_process_bindings=reasoned)
    assert (PLAN,CLAIMS)==before
    return result,sent


def test_valid_role_correction_rechecks_same_requirements_and_preserves_answer():
    result,sent=run();assert result['status']=='checked' and not result['gaps'] and len(sent)==2
    note=result['processBindingCorrection'];assert note['status']=='corrected' and note['inputDigest'] and note['resultDigest']
    assert sent[0][0]==sent[1][0]=='verify_answer_coverage' and sent[1][2]['max_tokens']<=sent[0][2]['max_tokens']
    assert sent[1][3]['use_reserve'] is True
    data=json.loads(sent[1][1].split('Frozen review inputs:\n',1)[1]);assert data['acceptedAnswer'][0]['text']==CLAIMS[0]['text']


@pytest.mark.parametrize('mode',['foreign','unbound','extra','wrong_id','overlap','purpose','malformed','missing','truncated'])
def test_invalid_correction_keeps_uncertain_gap_without_another_call_or_prose_rewrite(mode):
    result,sent=run(mode);assert result['gaps'] and len(sent)==2 and result['processBindingCorrection']['status']=='invalid_response'
    assert result['gaps'][0]['auditStatus']=='binding_unresolved'
    targeted=prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},result,defer_binding_errors=True,defer_invalid_process_reviews=True)
    assert targeted['accepted']==CLAIMS and targeted['rejected']==[] and targeted['deferredAuditGaps']


def test_correction_can_report_real_missing_explanation_without_fabricating_a_role():
    result,sent=run('partial');assert len(sent)==2 and result['processBindingCorrection']['status']=='corrected' and result['gaps']
    targeted=prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},result,defer_binding_errors=True,defer_invalid_process_reviews=True)
    assert targeted['rejected'][0]['reason']=='answer_incomplete' and not targeted.get('deferredAuditGaps')


def test_budget_denial_leaves_audit_uncertain_and_never_approves_or_rewrites_answer():
    result,sent=run('budget');assert result['processBindingCorrection']['status']=='not_started_budget' and result['gaps'] and len(sent)==2


def test_unknown_propagates_for_existing_ledger_pause_semantics():
    with pytest.raises(DeepResearchError,match='Observe original'):run('unknown')


@pytest.mark.parametrize('initial',['valid','partial'])
def test_valid_or_semantically_partial_original_review_does_not_trigger_binding_correction(initial):
    result,sent=run(initial=initial);assert len(sent)==1 and result['processBindingCorrection']['status']=='not_needed'
    assert bool(result['gaps']) is (initial=='partial')


def test_old_profile_never_sends_correction_or_adds_new_metadata():
    result,sent=run(activate=False);assert len(sent)==1 and result['gaps'] and 'processBindingCorrection' not in result
    assert prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},result,defer_binding_errors=True)['rejected']


def test_capacity_is_checked_before_correction_dispatch():
    from services.deep_research.request_coverage import contract,normalize
    req=contract(PLAN,Q,process_explanations=True);raw=[{'obligationId':'o','checks':[{'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'text'}],'reason':'Fixture.','processLinks':links('wrong')} for c in req[0]['checks']]}]
    normalized=normalize(raw,req,claims=CLAIMS,process_explanations=True,distinct_roles=True,literal_limits=True)
    invoke=Mock();old=deepcopy((raw,normalized));a,b,n=correct('r',raw,normalized,req,CLAIMS,invoke,json.loads,max_bytes=1,output_tokens=3500)
    assert (a,b)==old and n['status']=='not_started_capacity';invoke.assert_not_called()


@pytest.mark.parametrize('value',[None,True,'1',0,3])
def test_profile_requires_exact_server_version(value):
    assert not enabled({**policy(),KEY:value})


def test_profile_cannot_be_activated_without_full_existing_coverage_guards():
    assert enabled(policy())
    for key in policy():assert not enabled({k:v for k,v in policy().items() if k!=key})


@pytest.mark.parametrize('bad',[None,1,'1'])
def test_audit_switch_is_strict_boolean(bad):
    with pytest.raises(ValueError):audit_final_answer('r',Q,PLAN,CLAIMS,[],Mock(),json.loads,correct_process_bindings=bad)


def test_server_owned_profile_is_immutable_and_does_not_migrate_legacy(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':Q,KEY:False},start_async=False)
        assert type(row[KEY]) is int and row[KEY]==2
        assert enabled({**row,'state':{**row['state'],'outputKind':'claim_verification'}})
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(row['runId'],lambda r:{**r,KEY:True})
        old=deepcopy(row);old.pop(KEY);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,KEY:1})
    finally:facade.shutdown()


@pytest.mark.parametrize('whole',[False,True])
def test_new_deferral_keeps_binding_uncertainty_separate_from_other_real_content_gaps(whole):
    from test_deep_research_review_binding_routing import case
    report,verified,audit=case();gap=audit['gaps'][0];gap['wholeQuestion']=whole
    audit['verdicts'][0]['processAudits'][0]['errors']=['unbound_process_request']
    c2={'claimId':'c2','text':'Incomplete answer','obligationIds':['o2']};report['claims'].append(c2);verified['accepted'].append(c2)
    audit['gaps'].append({'obligationId':'o2','question':'Explain second operation'});audit['criterionGaps']={'o2':['Actual missing requirement']}
    audit['verdicts'].append({'obligationId':'o2','status':'missing','bindings':[]})
    result=prepare_coverage_repair(report,verified,audit,defer_binding_errors=True,defer_invalid_process_reviews=True)
    assert [x['claimId'] for x in result['accepted']]==['c1'] and [x['claimId'] for x in result['rejected']]==['c2']
    assert result['deferredAuditGaps']==[gap]


@pytest.mark.parametrize('kind',['experiment_design','unsupported'])
def test_actual_graph_does_not_send_new_policy_into_incompatible_coverage_modes(kind):
    from services.deep_research.graph import make_verify_node
    from unittest.mock import patch
    record={**policy(),'question':Q,'state':{'outputKind':kind,'reportBody':{'claims':[]},'plan':[],'evidence':[]},'budget':{}}
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    result=make_verify_node(lambda *_:{'accepted':[],'rejected':[]},None,update,llm_invoke=Mock())({'run_id':'r'})
    assert 'error_code' not in result
    assert 'coverageBindingCorrectionContractVersion' not in record['state']['verifiedReport']['answerCoverage']


def test_actual_graph_defers_failed_audit_without_attempting_text_repair():
    from services.deep_research.graph import make_verify_node
    from unittest.mock import patch
    audit,_=run('unbound')
    record={**policy(),'question':Q,'state':{'outputKind':'claim_verification','reportBody':{'claims':deepcopy(CLAIMS)},'plan':PLAN,'evidence':[]},'budget':{}}
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    invoke=Mock(side_effect=AssertionError('No scientific-prose repair for unresolved review binding'))
    with patch('services.deep_research.final_coverage.audit_final_answer',return_value=deepcopy(audit)):
        make_verify_node(lambda *_:{'accepted':deepcopy(CLAIMS),'rejected':[]},None,update,llm_invoke=invoke)({'run_id':'r'})
    invoke.assert_not_called();assert record['state']['deferredAuditGaps']
    assert not record['state'].get('repairAttempted') and record['state']['verifiedReport']['answerCoverage']['gaps']


@pytest.mark.parametrize('failure',['unknown','invalid'])
@pytest.mark.parametrize('reasoned',[False,True])
def test_real_ledger_recovery_reuses_original_review_and_never_resends_correction(tmp_path,failure,reasoned):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from llm.provider import LLMResult,LLMUsage,LLMProviderError
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':Q,'state':{'outputKind':'claim_verification'},'structuredOutputContractVersion':15,
        'budget':{'maxModelCalls':6,'maxTokens':100000,'maxWallClockSeconds':180,'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r')
    def reply(request):
        if request.prompt.startswith(GUIDANCE):
            if failure=='unknown':raise LLMProviderError('fixture timeout',provider='fixture',model='fixture',retryable=True)
            content='[]'
        else:
            requirements=inputs(request.prompt)['requirements']
            rows=[{'obligationId':o['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'text'}],'reason':'Actual operation exists.','processLinks':links('生成深度' if o['obligationId']=='o' else '深度图')} for c in o['checks']]} for o in requirements]
            content=json.dumps(rows)
        return LLMResult(provider='fixture',model='fixture',content=content,usage=LLMUsage(10,10,20),finish_reason='stop')
    client=Mock();client.invoke.side_effect=reply
    tracked=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,run_record_fn=repo.require_run)
    def audit():return audit_final_answer('r',Q,PLAN,CLAIMS,[],tracked,json.loads,request_contract=5,diagnostics=True,
        shared_decision_inputs=True,consolidated_instructions=True,literal_limits=True,correct_process_bindings=True,reasoned_process_bindings=reasoned)
    if failure=='unknown':
        with pytest.raises(LLMProviderError):audit()
    else:assert audit()['processBindingCorrection']['status']=='invalid_response'
    original=deepcopy(repo.list_calls('r'));assert len(original)==2 and client.invoke.call_count==2
    if failure=='unknown':
        with pytest.raises(DeepResearchError):audit()
    else:assert audit()['processBindingCorrection']['status']=='invalid_response'
    assert repo.list_calls('r')==original and client.invoke.call_count==2
    assert original[0]['settled'] and bool(original[1]['settled']) is (failure!='unknown')


@pytest.mark.parametrize('error',['missing_process_links','invalid_process_link','invalid_process_binding','unbound_process_request','ambiguous_process_excerpt','unbound_process_excerpt','purpose_or_result_not_operation','overlapping_process_roles'])
def test_all_known_invalid_positive_process_proofs_stay_uncertain_under_new_policy(error):
    from test_deep_research_review_binding_routing import case
    report,verified,audit=case();audit['verdicts'][0]['processAudits'][0]['errors']=[error]
    before=deepcopy((report,verified,audit))
    result=prepare_coverage_repair(report,verified,audit,defer_binding_errors=True,defer_invalid_process_reviews=True)
    assert result['rejected']==[] and result['accepted']==verified['accepted'] and result['deferredAuditGaps']==audit['gaps']
    assert (report,verified,audit)==before and audit['verdicts'][0]['status']=='partial'


def test_unresolved_binding_response_never_becomes_an_answer_deficiency():
    result,sent=run('unresolved');assert len(sent)==2 and result['processBindingCorrection']['status']=='unresolved_response'
    assert result['gaps'] and result['gaps'][0]['auditStatus']=='binding_unresolved'
    targets=prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},result,defer_binding_errors=True,defer_invalid_process_reviews=True)
    assert targets['rejected']==[] and targets['deferredAuditGaps']
