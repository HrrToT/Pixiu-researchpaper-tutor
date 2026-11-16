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
