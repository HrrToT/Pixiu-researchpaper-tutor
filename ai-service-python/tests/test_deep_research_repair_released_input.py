from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.repair_budget import repair_prompt_byte_limit
from services.deep_research.contracts import check_budget_limits,DeepResearchError
from services.deep_research.repair import repair_rejected


def budget():
    return {'maxTokens':100000,'reserveTokens':50000,'tokens':57635,'normalTokens':31935,
            'releasedReserveTokens':24300,'finalizationBudgetVersion':1,
            'maxModelCalls':18,'reserveModelCalls':5,'modelCalls':6,'reservedModelCalls':5,
            'maxWallClockSeconds':360,'elapsedSeconds':259}


def test_saved_budget_preflight_matches_ledger_without_releasing_or_minting_tokens():
    b=budget();before=deepcopy(b)
    assert repair_prompt_byte_limit(b,5120)==11921
    cap=repair_prompt_byte_limit(b,5120,released_finalization=True)
    assert cap==24000
    cost=cap+5120+1024
    admitted={**b,'tokens':b['tokens']+cost,'normalTokens':b['normalTokens']+cost,'modelCalls':b['modelCalls']+1}
    assert check_budget_limits(admitted) is None
    assert check_budget_limits(admitted,allow_released_reserve=False)=='normalTokens'
    assert b==before


@pytest.mark.parametrize('value',[0,-1,True,'24300',50001,None])
def test_missing_or_invalid_released_tokens_cannot_borrow_protected_reserve(value):
    b={**budget(),'releasedReserveTokens':value};before=deepcopy(b)
    assert repair_prompt_byte_limit(b,5120,released_finalization=True)==11921
    assert b==before


@pytest.mark.parametrize('version',[None,True,0,2])
def test_release_requires_exact_server_budget_version(version):
    b={**budget(),'finalizationBudgetVersion':version}
    assert repair_prompt_byte_limit(b,5120,released_finalization=True)==11921


def test_global_remaining_tokens_still_bound_repair():
    b={**budget(),'tokens':99000}
    assert repair_prompt_byte_limit(b,5120,released_finalization=True)==0


@pytest.mark.parametrize('value',[1,None,'true'])
def test_release_policy_is_strict_boolean(value):
    with pytest.raises(ValueError):repair_prompt_byte_limit(budget(),released_finalization=value)


def inputs():
    return {'claims':[{'claimId':'c','kind':'reported','text':'Original statement.','evidenceRefs':[]}]}, {
        'accepted':[],'rejected':[{'claimId':'c','reason':'unresolved'}]}


def preparer(report,verification,evidence,question,**kwargs):
    from services.deep_research.contracts import BudgetExhaustedError
    if kwargs['max_prompt_bytes']<16000:
        raise BudgetExhaustedError('repairEvidenceBytes',kwargs['max_prompt_bytes'],16000)
    return {'prompt':'x'*16000,'originals':{'c':report['claims'][0]},'aliases':{},'allowed':{'c':[]}}


@pytest.mark.parametrize('released',[False,True])
def test_each_batch_rechecks_current_ledger_credit_before_dispatch(monkeypatch,released):
    monkeypatch.setattr('services.deep_research.repair._prepare_repair',preparer)
    report,verification=inputs();send=Mock(return_value={'content':'[]'});b=budget();before=deepcopy(b)
    result=repair_rejected(report,verification,[],'Question',Mock(),json.loads,
        max_prompt_bytes=24000,current_budget=lambda:b,invoke_request=send,released_finalization=released)
    assert result==[] and send.call_count==int(released) and b==before


def test_pending_unknown_cannot_switch_release_policy_or_be_replayed(monkeypatch):
    monkeypatch.setattr('services.deep_research.repair._prepare_repair',preparer)
    report,verification=inputs();states=[];send=Mock(side_effect=DeepResearchError('unresolved_unknown','Unsettled'))
    with pytest.raises(DeepResearchError) as error:
        repair_rejected(report,verification,[],'Question',Mock(),json.loads,max_prompt_bytes=24000,
            current_budget=budget,invoke_request=send,checkpoint=states.append,released_finalization=True)
    assert error.value.code=='unresolved_unknown' and send.call_count==1 and states[-1]['pending']
    with pytest.raises(DeepResearchError) as error:
        repair_rejected(report,verification,[],'Question',Mock(),json.loads,max_prompt_bytes=24000,
            current_budget=budget,invoke_request=send,batch_state=states[-1],released_finalization=False)
    assert error.value.code=='invalid_repair_plan' and send.call_count==1
