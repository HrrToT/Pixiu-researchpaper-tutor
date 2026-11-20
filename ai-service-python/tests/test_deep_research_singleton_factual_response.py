from copy import deepcopy
import json
import pytest
from services.deep_research.factual_decision import decode
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_decision import checker,response,target,evidence


@pytest.mark.parametrize('supported',[False,True])
def test_exact_singleton_preserves_the_explicit_decision_and_all_scientific_fields(supported):
    raw=response(supported);before=deepcopy(raw)
    actual=decode(raw,singleton_claim_id='c')[0]
    assert actual['scopeAudit']==raw['scopeAudit'] and raw==before
    assert actual['status']==('passed' if supported else 'failed')
    assert actual['factualResponseEnvelope']=={'version':1,'kind':'single_exact_target_object'}
    assert all(actual[k]==v for k,v in raw.items())
    with pytest.raises(DeepResearchError):decode(raw)


@pytest.mark.parametrize('mutation',['wrong_id','missing_field','status','verdict','numeric_bool','wrong_path','extra_field'])
def test_singleton_wrapper_never_repairs_invalid_or_conflicting_scientific_fields(mutation):
    raw=response()
    if mutation=='wrong_id':raw['claimId']='other'
    if mutation=='missing_field':raw['scopeAudit'].pop('premises')
    if mutation=='status':raw['status']='failed'
    if mutation=='verdict':raw['scopeAudit']['verdict']='passed'
    if mutation=='numeric_bool':raw['scopeAudit']['supported']=1
    if mutation=='wrong_path':raw['scopeAudit']['statementPath']=['conditions']
    if mutation=='extra_field':raw['extra']='unrequested'
    with pytest.raises(DeepResearchError):decode(raw,singleton_claim_id='c')


def test_live_checker_opt_in_retains_evidence_binding_and_negative_decision_checks():
    invoke=lambda **_: {'content':json.dumps(response()),'finishReason':'stop'}
    assert checker(invoke,singleton_factual_response=True)([target()],evidence())[0]['status']=='passed'
    with pytest.raises(DeepResearchError):checker(invoke)([target()],evidence())
    raw=response();raw['scopeAudit']['premises'][0]['evidenceId']='foreign'
    assert checker(lambda **_: {'content':json.dumps(raw)},singleton_factual_response=True)([target()],evidence())[0]['status']=='failed'
    raw=response(False);raw['reason']='This is fully supported.'
    assert checker(lambda **_: {'content':json.dumps(raw)},singleton_factual_response=True)([target()],evidence())[0]['status']=='failed'


def test_multiple_targets_cannot_use_one_singleton_and_truncation_stays_invalid():
    with pytest.raises(DeepResearchError):
        checker(lambda **_: {'content':json.dumps(response())},singleton_factual_response=True)(
            [target(),{**target(),'claimId':'other'}],evidence())
    with pytest.raises(DeepResearchError):
        checker(lambda **_: {'content':json.dumps(response()),'finishReason':'length'},singleton_factual_response=True)([target()],evidence())
