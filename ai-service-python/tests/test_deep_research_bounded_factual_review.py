from copy import deepcopy
from datetime import datetime, UTC
from unittest.mock import Mock
import json
import pytest

from services.deep_research.factual_review import OPTION,admission,enabled
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker,BudgetedSemanticChecker
from services.deep_research.verification import verify_claims
from test_deep_research_synthesis_premises import claim,evidence


def record():
    return {'factualReviewContractVersion':1,'question':'比较，450字以内。',
        'state':{'outputKind':'paper_comparison'},'budget':{'maxWallClockSeconds':360,'elapsedSeconds':286}}


def history():
    return [{'node':'verify','tool':'llm_invoke','status':'succeeded','settled':True,
        'argsDigest':'previous','reservedAt':'2026-10-20T07:11:00Z','completedAt':'2026-10-20T07:11:52Z'},
        {'node':'verify','tool':'llm_invoke','status':'succeeded','settled':True,
        'argsDigest':'other','reservedAt':'2026-10-20T07:11:52Z','completedAt':'2026-10-20T07:12:55Z'}]


def test_observed_long_reviews_and_final_coverage_prevent_known_late_send_without_weakening_old_path():
    current=record();rows=history();before=deepcopy((current,rows))
    result=admission(current,rows,'new-request')
    assert result=={'allowed':False,'remainingSeconds':74.0,'requiredSeconds':113.75,'observedSettledReviews':2}
    assert (current,rows)==before
    assert admission({**current,'factualReviewContractVersion':None},rows,'new-request')=={'allowed':True}
    assert admission({**current,'budget':{**current['budget'],'elapsedSeconds':200}},rows,'new-request')['allowed']


def test_live_clock_and_no_history_keep_a_finite_review_and_coverage_floor():
    current=record();current['startedAt']='2026-10-20T07:00:00Z';current['budget']['elapsedSeconds']=0
    decision=admission(current,[],'new',now=datetime(2026,10,20,7,5,tzinfo=UTC))
    assert decision['remainingSeconds']==60 and decision['requiredSeconds']==75 and not decision['allowed']


@pytest.mark.parametrize('status,settled',[('succeeded',True),('unknown',False),('pending',False)])
def test_existing_request_reaches_original_ledger_guard_even_after_time_expires(status,settled):
    current=record();current['budget']['elapsedSeconds']=360
    rows=[{**history()[0],'argsDigest':'same','status':status,'settled':settled}]
    assert admission(current,rows,'same')=={'allowed':True,'existingRequest':True}


def test_low_effort_profile_is_reserved_and_fingerprinted_before_send_with_original_audits():
    from llm.provider import LLMResult,LLMUsage
    provider=Mock();provider.invoke.return_value=LLMResult(content='[]',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False));complete=Mock()
    current=record();current['budget']['elapsedSeconds']=0
    tracked=TrackedLLMInvoker(provider,reserve,complete,run_record_fn=lambda _:current,call_history_fn=lambda _:[])
    tracked('r','verify','unchanged original quotes and audits',{OPTION:True})
    sent=provider.invoke.call_args.args[0]
    assert sent.extra_body['max_tokens']==8192 and sent.extra_body['reasoning_effort']=='low'
    assert sent.extra_body['thinking']=={'type':'enabled'} and OPTION not in sent.extra_body
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(sent.prompt.encode())+1024+8192
    assert research_model_options('verify',{})['max_tokens']==16384
    assert research_model_options('verify',{})['reasoning_effort']=='high'
    with pytest.raises(ValueError):research_model_options('extract',{OPTION:True})


def test_denied_new_request_has_zero_reservations_and_sends_and_is_not_a_semantic_pass():
    current=record();provider=Mock();reserve=Mock();complete=Mock()
    tracked=TrackedLLMInvoker(provider,reserve,complete,run_record_fn=lambda _:current,call_history_fn=lambda _:history())
    checker=BudgetedSemanticChecker(tracked,'r',bounded_factual_review=True)
    target=claim('A uses an observed method.');support=[evidence('e','A uses an observed method.')]
    result=verify_claims([target],support,checker)
    assert not result['accepted'] and result['rejected'][0]['executionState']=='not_started'
    assert result['rejected'][0]['reviewTimeAdmission']['allowed'] is False
    assert '尚未核验' in result['rejected'][0]['detail']
    provider.invoke.assert_not_called();reserve.assert_not_called();complete.assert_not_called()


def test_settled_response_reuse_and_unknown_ledger_guard_are_not_replaced_by_time_refusal():
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.contracts import UnknownCallError
    current=record();current['budget']['elapsedSeconds']=0;rows=[]
    provider=Mock();provider.invoke.return_value=LLMResult(content='[]',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False))
    tracked=TrackedLLMInvoker(provider,reserve,Mock(),run_record_fn=lambda _:current,call_history_fn=lambda _:rows)
    tracked('r','verify','same immutable request',{OPTION:True})
    identity=reserve.call_args.kwargs['args_digest'];current['budget']['elapsedSeconds']=360
    rows.append({**history()[0],'argsDigest':identity})
    reserve.return_value=({'callId':'c','result':{'content':'saved verdict'}},True)
    assert tracked('r','verify','same immutable request',{OPTION:True})['content']=='saved verdict'
    assert provider.invoke.call_count==1
    rows[0].update(status='unknown',settled=False)
    reserve.side_effect=UnknownCallError('c')
    with pytest.raises(UnknownCallError):tracked('r','verify','same immutable request',{OPTION:True})
    assert provider.invoke.call_count==1


def test_refusal_does_not_discard_prior_independently_verified_claims():
    targets=[claim('First observed method.'),{**claim('Second unreviewed method.'),'claimId':'c2'}]
    support=[evidence('e','First and second observed methods.')]
    invoke=Mock(side_effect=[{'content':json.dumps([{'claimId':'c','status':'passed'}])},
        {'notStarted':'factual_review_time_budget','admission':{'allowed':False}}])
    checker=BudgetedSemanticChecker(invoke,'r',bounded_factual_review=True,isolate_factual_claims=True)
    result=verify_claims(targets,support,checker)
    assert [c['claimId'] for c in result['accepted']]==['c']
    assert result['rejected'][0]['claimId']=='c2' and result['rejected'][0]['executionState']=='not_started'


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_server_profile_is_frozen_and_never_applies_to_long_answers_or_experiments(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'比较，450字以内。',
            'deferStart':True,'factualReviewContractVersion':replacement},start_async=False)
        assert p['factualReviewContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(p['runId'],lambda r:{**r,'factualReviewContractVersion':replacement})
    finally:facade.shutdown()
    current=record();current['factualReviewContractVersion']=replacement
    assert not enabled(current)
    for question,kind in [('无字数上限','paper_comparison'),('1000字以内','claim_verification'),('300字以内','experiment_design')]:
        assert not enabled({**record(),'question':question,'state':{'outputKind':kind}})
