from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.factual_decision import decode,eligible
from services.deep_research.tools import BudgetedSemanticChecker


def response(supported=True):
    return {'claimId':'c','reason':'The supplied observation supports the stated setting.' if supported else 'Scope is unresolved.',
            'scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded','supported':supported,
                          'statementPath':['text'],'premises':[{'evidenceId':'E1','path':['quote']}]}}


def target():
    return {'claimId':'c','text':'Method A retained quality at setting 12.','kind':'reported',
            'conditions':{},'evidenceRefs':['own']}


def evidence():
    return [{'evidenceId':'own','quote':'Method A retained quality at setting 12.',
             'sourceWorkId':'p','sourceVersionId':'v'}]


def checker(invoke,**kw):
    return BudgetedSemanticChecker(invoke,'r',single_factual_decision=True,factual_scope=True,
                                  complete_factual_scope=True,audit_source_fields=True,audit_target_fields=True,**kw)


def test_single_decision_is_derived_only_from_explicit_boolean_and_keeps_all_audits():
    raw=response();raw['comparisonAudit']={'scope':'within_study','supportsClaim':True}
    before=deepcopy(raw);actual=decode([raw])[0]
    assert actual['status']=='passed' and actual['scopeAudit']==raw['scopeAudit']
    assert raw==before and decode([response(False)])[0]['status']=='failed'


@pytest.mark.parametrize('mutation',['legacy_failed','legacy_passed','nested_status','verdict','numeric_boolean',
                                   'missing_scope','missing_premises','narrow_path','empty_reason','extra_decision'])
def test_conflicting_legacy_or_incomplete_payload_never_gets_upgraded(mutation):
    raw=response()
    if mutation.startswith('legacy_'):raw['status']=mutation.split('_')[1]
    elif mutation=='nested_status':raw['scopeAudit']['status']='failed'
    elif mutation=='verdict':raw['verdict']='passed'
    elif mutation=='numeric_boolean':raw['scopeAudit']['supported']=1
    elif mutation=='missing_scope':raw.pop('scopeAudit')
    elif mutation=='missing_premises':raw['scopeAudit'].pop('premises')
    elif mutation=='narrow_path':raw['scopeAudit']['statementPath']=['conditions','setting']
    elif mutation=='empty_reason':raw['reason']=''
    else:raw['decision']='supported'
    with pytest.raises(DeepResearchError,match='未改判') as caught:decode([raw])
    assert caught.value.details['responseState']=='received_invalid'


def test_complete_fact_still_needs_valid_own_premises_and_actual_scope():
    sent=[]
    def invoke(**kw):
        sent.append(kw);return {'content':json.dumps([response()]),'finishReason':'stop'}
    result=checker(invoke)([target()],evidence())
    assert result[0]['status']=='passed'
    assert 'SINGLE WHOLE-CLAIM' in sent[0]['prompt'] and '"status": "passed" or "failed"' not in sent[0]['prompt']
    assert 'Return\nfailed if any substantive clause' not in sent[0]['prompt']
    assert sent[0]['use_reserve'] is True and sent[0]['node']=='verify'
    bad=response();bad['scopeAudit']['premises'][0]['evidenceId']='foreign'
    assert checker(lambda **_: {'content':json.dumps([bad])})([target()],evidence())[0]['status']=='failed'
    strong=response();strong['scopeAudit']['claimStrength']='universal'
    assert checker(lambda **_: {'content':json.dumps([strong])})([target()],evidence())[0]['status']=='failed'


def test_negative_boolean_cannot_be_overridden_by_positive_reason_or_other_audits():
    raw=response(False);raw['reason']='The claim is fully supported; should pass.'
    result=checker(lambda **_: {'content':json.dumps([raw])})([target()],evidence())
    assert result[0]['status']=='failed'


def test_semantic_counterfields_are_not_enough_to_hide_a_missing_comparison_audit():
    claim={**target(),'tableBindings':[{'evidenceId':'own','rowNumber':1},{'evidenceId':'own','rowNumber':2}]}
    raw=response()
    result=checker(lambda **_: {'content':json.dumps([raw])},comparison_reasoning=True)([claim],evidence())
    assert result[0]['status']=='failed' and '比较' in result[0]['reason']


def test_result_purpose_audit_is_still_required_after_positive_whole_fact_decision():
    claim={**target(),'text':'主表报告FPS为12。'}
    result=checker(lambda **_: {'content':json.dumps([response()])},result_attribution=True)([claim],evidence())
    assert result[0]['status']=='failed' and '归属' in result[0]['reason']


def test_original_numeric_hard_check_runs_before_the_new_semantic_protocol():
    from test_deep_research_verification import evidence as supported,claim as make_claim
    from services.deep_research.verification import verify_claims
    ev=supported();invoke=Mock()
    result=verify_claims([make_claim(ev,'速度为999 FPS')],[ev],checker(invoke))
    assert not result['accepted'] and result['rejected'][0]['reason']=='numeric_mismatch'
    invoke.assert_not_called()


def test_another_targets_premises_cannot_license_a_positive_boolean():
    other={**target(),'claimId':'c2','text':'Method B retained quality.','evidenceRefs':['other']}
    other_evidence={'evidenceId':'other','quote':'Method B retained quality.'}
    second=response();second['claimId']='c2' # Still bound to E1, belonging only to c.
    result=checker(lambda **_: {'content':json.dumps([response(),second])})([target(),other],[*evidence(),other_evidence])
    assert [(v['claimId'],v['status']) for v in result]==[('c','passed'),('c2','failed')]


def test_legacy_fact_protocol_keeps_negative_status_even_with_positive_audit():
    raw=response();raw['status']='failed';sent=[]
    def invoke(**kw):sent.append(kw);return {'content':json.dumps([raw])}
    result=BudgetedSemanticChecker(invoke,'r',factual_scope=True,complete_factual_scope=True)([target()],evidence())
    assert result[0]['status']=='failed' and 'SINGLE WHOLE-CLAIM' not in sent[0]['prompt']
    with pytest.raises(DeepResearchError):checker(invoke)([target()],evidence())
    with pytest.raises(DeepResearchError):
        BudgetedSemanticChecker(lambda **_: {'content':json.dumps([response()])},'r')([target()],evidence())


def test_proposals_and_incomplete_scope_modes_do_not_enter_new_protocol():
    assert eligible(True,[target()],True,True)
    assert not eligible(True,[{**target(),'kind':'proposal'}],True,True)
    assert not eligible(True,[target()],True,False)
    assert not eligible(1,[target()],True,True)
    proposal={**target(),'kind':'proposal'};sent=[]
    def invoke(**kw):sent.append(kw);return {'content':json.dumps([{'claimId':'c','status':'failed'}])}
    assert checker(invoke)([proposal],evidence())[0]['status']=='failed'
    assert 'SINGLE WHOLE-CLAIM' not in sent[0]['prompt']


@pytest.mark.parametrize('mode',['length','duplicate','missing','budget','unknown'])
def test_incomplete_or_unknown_results_propagate_without_retry(mode):
    calls=[]
    def invoke(**kw):
        calls.append(kw)
        if mode in ('budget','unknown'):raise DeepResearchError(mode,'Original guard')
        rows=[] if mode=='missing' else [response(),response()] if mode=='duplicate' else [response()]
        return {'content':json.dumps(rows),'finishReason':'length' if mode=='length' else 'stop'}
    with pytest.raises(DeepResearchError):checker(invoke)([target()],evidence())
    assert len(calls)==1


def test_flag_is_server_owned_and_old_records_are_not_opted_in(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'run.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'核对','deferStart':True,
                            'factualDecisionContractVersion':0},start_async=False)
        assert run['factualDecisionContractVersion']==1
        assert facade._build_semantic_checker(run['runId'],Mock())._single_factual_decision() is True
        for value in (None,0,True,'1',2):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run['runId'],lambda r:{**r,'factualDecisionContractVersion':value})
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('factualDecisionContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        assert facade._build_semantic_checker('old',Mock())._single_factual_decision() is False
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'继续','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()


def test_invalid_new_repair_response_retains_prior_independently_checked_content():
    import test_deep_research_repair_verification_failure as prior
    from unittest.mock import patch
    raw={'claimId':'repair','status':'failed','reason':'Legacy response is not a new decision.'}
    get,update,node,dispatch,rewrite=prior.fixture(response={'content':json.dumps([raw]),'finishReason':'stop'})
    def modern(invoker,run_id):
        return BudgetedSemanticChecker(invoker,run_id,single_factual_decision=True,
                                       factual_scope=True,complete_factual_scope=True)
    with patch.object(prior,'BudgetedSemanticChecker',side_effect=modern), \
         patch('services.deep_research.final_coverage.audit_final_answer',return_value=prior.coverage()):
        result=node({'run_id':'r'})
    assert result['claim_ids']==['keep']
    assert get()['state']['repairStatus']=='verification_invalid_response'
    assert get()['state']['repairVerificationError']['responseState']=='received_invalid'
    assert dispatch.call_count==rewrite.call_count==1
