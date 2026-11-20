from copy import deepcopy
import json

import pytest

from services.deep_research.review_alignment import declaration_links,DESIGN_POLICY,POLICY,enabled,factorial_reference
from services.deep_research.prospective_review import policy
from services.deep_research.design_review_policy import REVIEW_DESIGN_POLICY,REVIEW_FACTORIAL_REFERENCE
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_direct_audit_fields import analysis_and_verdict
from test_deep_research_shared_experiment_repair import inputs


def proposals():
    analysis,_=analysis_and_verdict()
    analysis['executionSpec']['effects']={'quality_delta':'Q1-Q0','storage_delta':'S1-S0','time_delta':'T1-T0'}
    hyp={'claimId':'h','kind':'hypothesis','designRole':'hypothesis','designContractVersion':2,
        'hypothesisContractVersion':1,'text':'An unexecuted descriptive comparison; no direction predicted.',
        'evidenceRefs':[],'executionSpec':{'statement':'Explore the tradeoff.',
            'analysisClaimId':analysis['claimId'],'effectKeys':['quality_delta','storage_delta','time_delta'],'purpose':'explore'}}
    return hyp,analysis


def test_index_reports_actual_linked_keys_without_approving_formulas_or_mutating_declarations():
    hyp,analysis=proposals();before=deepcopy([hyp,analysis]);rows=declaration_links([hyp,analysis])
    assert rows==[{'hypothesisId':'h','analysisId':analysis['claimId'],
        'requestedKeys':['quality_delta','storage_delta','time_delta'],
        'presentKeys':['quality_delta','storage_delta','time_delta'],'missingKeys':[]}]
    assert [hyp,analysis]==before and 'verified' not in json.dumps(rows)
    analysis['executionSpec']['effects']['time_delta']="unsafe_text(); not evaluated"
    assert declaration_links([hyp,analysis])==rows


def test_actual_missing_keys_are_not_filled_from_other_analysis_or_similarity():
    hyp,analysis=proposals();del analysis['executionSpec']['effects']['time_delta']
    unrelated=deepcopy(analysis);unrelated['claimId']='other';unrelated['executionSpec']['effects']['time_delta']='T1-T0'
    row=declaration_links([hyp,analysis,unrelated])[0]
    assert row['missingKeys']==['time_delta'] and row['presentKeys']==['quality_delta','storage_delta']


@pytest.mark.parametrize('change',['missing','duplicate','wrong_role','wrong_kind','wrong_contract'])
def test_absent_ambiguous_or_wrong_analysis_is_never_guessed(change):
    hyp,analysis=proposals();rows=[hyp,analysis]
    if change=='missing':rows.pop()
    elif change=='duplicate':rows.append(deepcopy(analysis))
    elif change=='wrong_role':analysis['designRole']='limits'
    elif change=='wrong_kind':analysis['kind']='reported'
    else:analysis['designContractVersion']=True
    result=declaration_links(rows)[0]
    assert result['analysisStatus'] in ('missing_or_ambiguous','wrong_role_or_contract')
    assert 'presentKeys' not in result and 'missingKeys' not in result


@pytest.mark.parametrize('change',['hyp_version','contract','kind_list','duplicate_id'])
def test_unversioned_or_ambiguous_hypotheses_receive_no_inferred_links(change):
    hyp,analysis=proposals();rows=[hyp,analysis]
    if change=='hyp_version':hyp['hypothesisContractVersion']='1'
    elif change=='contract':hyp['designContractVersion']=True
    elif change=='kind_list':hyp['kind']=[]
    else:rows.append(deepcopy(hyp))
    assert declaration_links(rows)==[]


@pytest.mark.parametrize('change',['effect_mapping','formula','decision','hypothesis'])
def test_malformed_settings_stay_explicit_errors_not_an_empty_success_packet(change):
    hyp,analysis=proposals()
    if change=='effect_mapping':analysis['executionSpec']['effects']=[]
    elif change=='formula':analysis['executionSpec']['effects']['time_delta']=None
    elif change=='decision':analysis['executionSpec']['decision']={'mode':[]}
    else:hyp['executionSpec']['effectKeys']=['quality_delta',True]
    row=declaration_links([hyp,analysis])[0]
    assert row.get('analysisSchemaErrors') or row.get('hypothesisSchemaErrors')
    if change=='effect_mapping':assert row['analysisStatus']=='invalid_effects_mapping'


def review(version):
    hyp,analysis=proposals();sent=[]
    def invoke(**request):
        sent.append(request)
        targets=json.JSONDecoder().raw_decode(request['prompt'].split('Claims:',1)[1].lstrip())[0]
        return {'content':json.dumps([{'claimId':c['claimId'],'status':'failed',
            'reason':'Original missing actual initialization or measurement.'} for c in targets])}
    result=BudgetedSemanticChecker(invoke,'offline',prospective_review=version,experiment_intent_review=3,
        research_question='Compare the whole stage quality/storage/extra training tradeoff; no isolated parameter attribution.').check_revisions([hyp,analysis],[],[])
    return sent,result


def test_new_review_replaces_conflicting_rules_and_receives_exact_field_presence():
    old,old_result=review(2);new,new_result=review(lambda:3)
    assert len(new)==len(old)==1 and new_result==old_result and all(r['status']=='failed' for r in new_result)
    prompt=new[0]['prompt']
    assert DESIGN_POLICY in prompt and POLICY in prompt and REVIEW_DESIGN_POLICY not in prompt
    assert policy(2) in old[0]['prompt'] and policy(2) not in prompt
    assert 'for isolated effects' in factorial_reference(3)
    assert 'ONLY to an actually requested' in prompt
    assert json.loads(prompt.split('Declared key presence (not scientific approval):\n')[1])==declaration_links(list(proposals()))
    assert len(prompt.encode())<=24000 and old[0]['extra_body']==new[0]['extra_body']


@pytest.mark.parametrize('version',[None,True,False,'3',0,4])
def test_unknown_or_wrong_type_does_not_enable_new_policy_or_change_legacy_reference(version):
    baseline,_=review(False);actual,_=review(version)
    assert actual==baseline and not enabled(version)
    assert factorial_reference(version)==REVIEW_FACTORIAL_REFERENCE


@pytest.mark.parametrize('version',[2,3])
def test_new_review_preserves_exact_direct_binding_checks_and_failed_status(version):
    analysis,verdict=analysis_and_verdict()
    checker=BudgetedSemanticChecker(lambda **_: {'content':json.dumps([verdict])},'offline',prospective_review=version)
    assert checker([analysis],inputs()[2])[0]['status']=='passed'
    verdict['designAudit']['effects']['value']={'wrong':'value'}
    assert checker([analysis],inputs()[2])[0]['status']=='failed'
    verdict['status']='failed';verdict['reason']='Unverified method.'
    assert checker([analysis],inputs()[2])[0]['status']=='failed'


def test_factual_claims_do_not_receive_proposed_choice_exemptions_or_presence_index():
    sent=[]
    def invoke(**request):
        sent.append(request);return {'content':json.dumps([{'claimId':'f','status':'failed','reason':'Unsupported author setting.'}])}
    result=BudgetedSemanticChecker(invoke,'offline',prospective_review=3)(
        [{'claimId':'f','kind':'reported','text':'Authors used this proposed size.','evidenceRefs':[]}],[])
    assert result[0]['status']=='failed'
    assert DESIGN_POLICY not in sent[0]['prompt'] and POLICY not in sent[0]['prompt']
    assert 'Declared key presence' not in sent[0]['prompt']
