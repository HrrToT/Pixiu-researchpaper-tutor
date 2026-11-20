from copy import deepcopy

import pytest

from services.deep_research.comparison_capacity import after_synthesis


def candidate():
    return {'stage':'synthesize','claimIsolationContractVersion':1,
            'recommendationReviewContractVersion':1,
            'budget':{'maxModelCalls':18,'modelCalls':7,'reservedModelCalls':1},
            'state':{'outputKind':'paper_comparison','reportBody':{'claims':[
                *[{'claimId':str(i),'kind':'reported','text':'Source-specific point'} for i in range(8)],
                {'claimId':'advice','kind':'proposal','text':'Conditional choice'}]}}}


def test_whole_candidate_uses_both_call_pools_and_keeps_a_final_audit_slot():
    record=candidate();before=deepcopy(record)
    result=after_synthesis(record)
    assert result['remainingModelCalls']==10
    assert result['minimumReviewCalls']==9 and result['minimumWholeAnswerAuditCalls']==1
    assert result['fitsCallLowerBound'] and result['callsBeyondLowerBound']==0
    assert not result['tokensAndTimeFitEstablished'] and not result['scientificApproval']
    assert record==before


def test_shortfall_does_not_remove_points_or_authorize_more_calls():
    record=candidate();record['budget']['reservedModelCalls']=2;before=deepcopy(record)
    result=after_synthesis(record)
    assert not result['fitsCallLowerBound'] and result['minimumAdditionalCalls']==10
    assert record==before and len(record['state']['reportBody']['claims'])==9


def test_unknown_verification_state_cannot_be_mistaken_for_a_fresh_candidate():
    record=candidate();record['stage']='verify'
    assert after_synthesis(record)['status']=='unsupported_policy'


@pytest.mark.parametrize('field,value',[('modelCalls',True),('reservedModelCalls',-1),('modelCalls',19)])
def test_invalid_call_accounting_is_rejected(field,value):
    record=candidate();record['budget'][field]=value
    with pytest.raises(ValueError):after_synthesis(record)


def populated_factual_record():
    from test_deep_research_comparison_intent import record,packets
    from services.deep_research.comparison_cells import compile_cells
    r=record();plan,payload=packets()
    draft=compile_cells(payload,plan,max_claims=8)
    draft['sources']=deepcopy(plan['sources'])
    evidence=[{'evidenceId':f'E{i+1}','sourceWorkId':w,'sourceVersionId':w+'-v1',
               'quote':'A method under stated conditions.','verification':{'literal':'passed'}}
              for i,w in enumerate(('left','right','other'))]
    r.update(runId='r',comparisonPlanningContractVersion=2,comparisonReviewBatchContractVersion=2)
    r['state']={'outputKind':'paper_comparison','comparisonCellDraft':draft,
                'reportBody':draft['report'],'evidence':evidence,
                'plan':[{'obligations':plan['requirements']}]}
    return r


@pytest.mark.parametrize('defect',['legacy','unresolved_cell','empty_cell','semantic_only','proposal'])
def test_initial_audit_deferral_requires_populated_factual_cells_and_an_actionable_hard_error(defect):
    from services.deep_research.comparison_capacity import defer_initial_audit
    r=populated_factual_record();v={'rejected':[{'claimId':'cmp_0_0','reason':'numeric_mismatch'}]}
    assert defer_initial_audit(r,v)
    if defect=='legacy':r['comparisonReviewBatchContractVersion']=1
    if defect=='unresolved_cell':r['state']['comparisonCellDraft']['layout'][0]['unresolved']=True
    if defect=='empty_cell':r['state']['comparisonCellDraft']['layout'][0]['claimIds']=[]
    if defect=='semantic_only':v['rejected'][0]['reason']='semantic_unresolved'
    if defect=='proposal':r['state']['reportBody']['claims'][0]['kind']='proposal'
    assert not defer_initial_audit(r,v)


@pytest.mark.parametrize('repair_outcome',['changed','empty','unchanged','budget','invalid','unknown','audit_budget'])
def test_production_verify_always_audits_after_deferred_repair_even_when_it_fails(repair_outcome):
    from unittest.mock import Mock,patch
    from services.deep_research.graph import make_verify_node
    from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
    r=populated_factual_record();claims=deepcopy(r['state']['reportBody']['claims'])
    rejected_id=claims[0]['claimId'];events=[]
    revised={**claims[0],'text':'修订后的明确限定论断。'}
    def update(rid,fn,**kwargs):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    def verify(targets,evidence,semantic):
        events.append('verify')
        if len(events)>1:
            if repair_outcome=='unknown':
                raise DeepResearchError('tool_execution_unknown','transport outcome unknown')
            if repair_outcome=='invalid':
                raise DeepResearchError('invalid_verification_response','invalid',{'responseState':'received_invalid'})
            if repair_outcome!='unchanged':return {'accepted':targets,'rejected':[]}
        return {'accepted':[c for c in targets if c['claimId']!=rejected_id],
                'rejected':[{'claimId':rejected_id,'reason':'numeric_mismatch'}]}
    def repair(*args,**kwargs):
        events.append('repair')
        if repair_outcome=='budget':raise BudgetExhaustedError('tokens',100,101)
        return [] if repair_outcome=='empty' else [claims[0] if repair_outcome=='unchanged' else revised]
    def audit(*args,**kwargs):
        events.append('audit')
        assert 'repair' in events
        if repair_outcome=='audit_budget':return {'status':'budget_exhausted','gaps':[{'obligationId':'unverified'}]}
        return {'status':'checked','gaps':[{'obligationId':'still_missing','missingEvidence':'test gap'}]}
    with patch('services.deep_research.repair.repair_rejected',side_effect=repair),patch(
            'services.deep_research.final_coverage.audit_final_answer',side_effect=audit) as audited:
        node=make_verify_node(verify,None,update,llm_invoke=Mock())
        if repair_outcome=='unknown':
            with pytest.raises(DeepResearchError,match='transport outcome unknown'):node({'run_id':'r'})
            assert 'audit' not in events and not r['state'].get('verifiedReport')
            return
        node({'run_id':'r'})
        before=list(events)
        node({'run_id':'r'})
        assert events==before  # Completed checkpoint does not reissue repair/audit.
    assert events[0:2]==['verify','repair'] and events[-1]=='audit' and events.count('audit')==1
    assert r['state']['initialAnswerCoverage']['status']=='deferred_factual_repair'
    result=r['state']['verifiedReport']
    assert result['answerCoverage']['gaps']
    assert result['answerCoverage']['status']==('budget_exhausted' if repair_outcome=='audit_budget' else 'checked')
    accepted_ids={c['claimId'] for c in result['verifiedClaims']}
    assert (rejected_id in accepted_ids)==(repair_outcome in ('changed','audit_budget'))


def test_exhausted_repair_audit_keeps_the_previously_checked_comparison():
    _assert_previously_checked_comparison_survives(6)


def test_named_condition_repair_keeps_the_previously_checked_comparison():
    _assert_previously_checked_comparison_survives(11)


def _assert_previously_checked_comparison_survives(authoring_version):
    from unittest.mock import Mock, patch
    from services.deep_research.answer_coherence import identity
    from services.deep_research.comparison_presentation import audit_digest
    from services.deep_research.graph import make_verify_node

    r = populated_factual_record()
    r.update(comparisonPlanningContractVersion=6, comparisonAuthoringContractVersion=authoring_version)
    from services.deep_research.authored_body import decode
    claims = [decode(c) for c in r['state']['reportBody']['claims']]
    rejected_id = claims[0]['claimId']
    first_check = {'accepted': claims[1:], 'rejected': [
        {'claimId': rejected_id, 'reason': 'semantic_unresolved'}]}
    revision = {**claims[0], 'text': 'Revised with scope.'}
    verify = Mock(side_effect=[first_check, {'accepted': [revision], 'rejected': []}])
    limit = {'kind': 'coveragePromptBytes', 'limit': 10, 'used': 2000}
    audits = []

    def audit(rid, question, plan, accepted, *args, comparison_cells, **kwargs):
        if audits:
            assert revision['claimId'] in {claim['claimId'] for claim in accepted}
            return {'status': 'budget_exhausted', 'budgetLimit': limit}
        checked = {'status': 'checked', 'comparisonPresentationDigest': audit_digest(comparison_cells, accepted),
                   'answerCoherence': {'contractVersion': 1, 'status': 'checked', 'coherent': True,
                                       'issues': [], 'answerDigest': identity(question, accepted)},
                   'gaps': [{'obligationId': 'mechanism', 'missingEvidence': 'Still missing.'}]}
        audits.append(checked)
        return checked

    def update(rid, fn, **kwargs):
        nonlocal r
        r = fn(deepcopy(r))
        return deepcopy(r)

    with patch('services.deep_research.repair.repair_rejected', return_value=[revision]), patch(
            'services.deep_research.final_coverage.audit_final_answer', side_effect=audit) as reviewer:
        make_verify_node(verify, None, update, llm_invoke=Mock())({'run_id': 'r'})

    state = r['state']
    assert reviewer.call_count == 2
    assert state['verifiedReport']['verifiedClaims'] == first_check['accepted']
    assert state['verifiedReport']['answerCoverage'] == audits[0]
    assert state['repairVerification']['accepted'] != first_check['accepted']
    assert state['repairReleaseDeferred'] == {'status': 'budget_exhausted', 'budgetLimit': limit}
