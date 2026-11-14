"""A decisive objection must survive verification and reach the repair request."""
from copy import deepcopy
import json

import pytest

from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.verification import make_evidence,verify_claims


def inputs():
    quote='A bounded finding.'
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},
                     quote,quote,location={},obligation_ids=[])
    claim={'claimId':'c','kind':'reported','text':quote,'conditions':{},'evidenceRefs':[ev['evidenceId']]}
    return claim,ev


def reason():
    return 'The supplied source supports this context. '*14+'However, the actual first applied step contradicts the asserted zero starting value.'


@pytest.mark.parametrize('flag',[False,True])
def test_complete_negative_reason_survives_only_for_new_contract(flag):
    claim,ev=inputs();text=reason();before=deepcopy((claim,ev));calls=[]
    def semantic(claims,evidence):calls.append((claims,evidence));return [{'claimId':'c','status':'failed','reason':text}]
    result=verify_claims([claim],[ev],semantic,complete_review_feedback=flag)
    assert not result['accepted'] and len(calls)==1
    detail=result['rejected'][0]['detail']
    assert detail==(text if flag else text[:400])
    assert ('However' in detail) is flag
    assert (claim,ev)==before


def test_legacy_default_result_is_byte_equivalent_to_explicit_off_policy():
    claim,ev=inputs();check=lambda *_:[{'claimId':'c','status':'failed','reason':reason()}]
    assert verify_claims([claim],[ev],check)==verify_claims([claim],[ev],check,complete_review_feedback=False)


@pytest.mark.parametrize('text',['prefix\nexact\t尾部事实。'*80,'first clause. '*1000,'A short unresolved reason.'])
def test_complete_feedback_is_literal_and_never_selectively_summarized(text):
    claim,ev=inputs()
    result=verify_claims([claim],[ev],lambda *_:[{'claimId':'c','status':'failed','reason':text}],complete_review_feedback=True)
    assert result['rejected'][0]['detail']==text


@pytest.mark.parametrize('bad',[None,0,1,'1'])
def test_policy_requires_strict_boolean_before_any_checker_call(bad):
    claim,ev=inputs()
    with pytest.raises(ValueError):verify_claims([claim],[ev],lambda *_:pytest.fail('No call'),complete_review_feedback=bad)


def test_full_feedback_does_not_change_passed_claim_or_hard_numeric_rejection():
    claim,ev=inputs();check=lambda *_:[{'claimId':'c','status':'passed','reason':reason()}]
    assert verify_claims([claim],[ev],check)==verify_claims([claim],[ev],check,complete_review_feedback=True)
    bad={**claim,'text':'A finding at 999 FPS.'}
    for flag in (False,True):
        result=verify_claims([bad],[ev],lambda *_:pytest.fail('Hard check first'),complete_review_feedback=flag)
        assert result['rejected'][0]['reason']=='numeric_mismatch'


def test_invalid_diagnostic_still_uses_safe_unresolved_reason_instead_of_untrusted_correction():
    from services.deep_research.review_diagnostics import bind
    claim,ev=inputs()
    verdict=bind({'claimId':'c','status':'failed','reason':'The correct coefficient is 0.999.','diagnosticFacts':[]},claim,[ev])
    result=verify_claims([claim],[ev],lambda *_:[verdict],complete_review_feedback=True)
    row=result['rejected'][0]
    assert row['executionState']=='received_invalid' and '0.999' not in json.dumps(row)
    assert row['detail']==verdict['reason'] and row['reviewDiagnosticAudit']['errors']


def test_unknown_checker_outcome_propagates_without_retry_or_repair():
    claim,ev=inputs();calls=[]
    def semantic(*_):calls.append(1);raise DeepResearchError('unknown_call','Observe the original call')
    with pytest.raises(DeepResearchError,match='Observe'):verify_claims([claim],[ev],semantic,complete_review_feedback=True)
    assert calls==[1]


def test_full_objection_reaches_actual_repair_request_without_new_facts_or_permissions():
    claim,ev=inputs();text=reason()
    checked=verify_claims([claim],[ev],lambda *_:[{'claimId':'c','status':'failed','reason':text}],complete_review_feedback=True)
    before=deepcopy((claim,ev,checked));calls=[]
    def invoke(prompt):calls.append(prompt);return {'content':'[]'}
    repair_rejected({'claims':[claim]},checked,[ev],'Explain the bounded finding.',invoke,json.loads)
    assert len(calls)==1 and text in calls[0] and 'However' in calls[0]
    assert (claim,ev,checked)==before


def test_full_reason_over_capacity_is_reported_without_prefix_fallback():
    claim,ev=inputs();text=reason()*200
    checked=verify_claims([claim],[ev],lambda *_:[{'claimId':'c','status':'failed','reason':text}],complete_review_feedback=True)
    assert checked['rejected'][0]['detail']==text
    with pytest.raises(BudgetExhaustedError):
        _prepare_repair({'claims':[claim]},checked,[ev],'Explain',max_prompt_bytes=24000)


def test_new_root_is_server_owned_immutable_and_legacy_factory_keeps_400_chars(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='completeReviewFeedbackContractVersion'
    claim,ev=inputs();check=lambda *_:[{'claimId':'c','status':'failed','reason':reason()}]
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',key:False},start_async=False)
        assert type(row[key]) is int and row[key]==1
        assert facade._get_verify_claims(row['runId'])([claim],[ev],check)['rejected'][0]['detail']==reason()
        old=deepcopy(row);old.pop(key);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        assert facade._get_verify_claims('old')([claim],[ev],check)['rejected'][0]['detail']==reason()[:400]
        for rid in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,key:2})
    finally:facade.shutdown()
