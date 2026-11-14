from copy import deepcopy
import json

import pytest

from services.deep_research.rejection_audit import validate,bind
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims
from test_deep_research_review_envelope import Capture,args


def data():return json.loads(args('data')['claims_text'])[0]


def finding(claim,**changes):
    return {'kind':'incomplete','claimId':claim['claimId'],'path':['executionSpec','seeds'],
        'value':deepcopy(claim['executionSpec']['seeds']),'reason':'已有种子，但还需明确其用途。',**changes}


def test_existing_seed_cannot_be_declared_absent_and_is_never_promoted_to_a_pass():
    c=data();v={'claimId':c['claimId'],'status':'failed','reason':'Missing seed.',
        'findings':[finding(c,kind='missing_field')]};v['findings'][0].pop('value')
    before=deepcopy((v,c));out=bind(v,[c])
    assert out['status']=='failed' and out['executionState']=='received_invalid'
    assert 'not_an_absent_schema_field' in out['rejectionAudit']['errors'][0]
    assert out['rejectionAudit']['originalReason']=='Missing seed.' and (v,c)==before


def test_absent_required_key_is_distinct_from_present_null_empty_or_invalid():
    c=data();v={'status':'failed','findings':[{'kind':'missing_field','claimId':c['claimId'],
        'path':['executionSpec','seeds'],'reason':'缺少种子字段。'}]}
    for value in [None,[],True,0]:
        c['executionSpec']['seeds']=value;assert validate(v,[c])
    del c['executionSpec']['seeds'];assert validate(v,[c])==[]
    c['designRole']='metrics';assert validate(v,[c])  # No invented metrics grammar.


@pytest.mark.parametrize('change',['value','bool_number','foreign_id','ambiguous_id','fake_path','bool_index','extra','blank_reason'])
def test_negative_bindings_reject_fabricated_values_paths_or_identity(change):
    c=data();c['executionSpec']['seeds']=[0];f=finding(c);context=[c]
    if change=='value':f['value']=[1]
    elif change=='bool_number':f['value']=[False]
    elif change=='foreign_id':f['claimId']='foreign'
    elif change=='ambiguous_id':context.append(deepcopy(c))
    elif change=='fake_path':f['path']=['executionSpec','invented']
    elif change=='bool_index':f['path']=['executionSpec','seeds',False];f['value']=0
    elif change=='extra':f['extra']='unsupported'
    else:f['reason']=' '
    assert validate({'status':'failed','findings':[f]},context)


def test_present_but_incomplete_value_has_exact_binding_without_scientific_approval():
    c=data();v={'claimId':c['claimId'],'status':'failed','reason':'Unbound model summary.',
        'findings':[finding(c)]};out=bind(v,[c])
    assert out['reason']==v['findings'][0]['reason'] and out['status']=='failed'
    assert out['rejectionAudit']['bindingState']=='verified'
    assert out['rejectionAudit']['scientificRejectionVerified'] is False


@pytest.mark.parametrize('findings',[None,[],{},[None]])
def test_missing_malformed_negative_audit_is_unreviewed(findings):
    c=data();out=bind({'claimId':c['claimId'],'status':'failed','findings':findings},[c])
    assert out['executionState']=='received_invalid'


def test_positive_verdict_with_negative_findings_is_not_accepted():
    c=data();v={'claimId':c['claimId'],'status':'passed','findings':[finding(c)]}
    assert bind(v,[c])['status']=='failed'
    assert bind({**v,'findings':[]},[c])=={**v,'findings':[]}


def test_model_cannot_supply_server_owned_execution_or_repair_annotations():
    c=data();v={'claimId':c['claimId'],'status':'passed','findings':[],
        'executionState':'received_invalid','rejectionAudit':{'bindingState':'invalid'}}
    result=bind(v,[c]);assert 'executionState' not in result and 'rejectionAudit' not in result


def test_actual_checker_binds_negative_response_and_verification_preserves_unreviewed_state():
    c={'claimId':'limits','kind':'proposal','designContractVersion':2,'designRole':'limits',
        'text':'This is an unexecuted single-scene plan.','evidenceRefs':[]}
    class Wire(Capture):
        def __call__(self,**request):
            self.sent.append(request)
            return {'content':json.dumps([{'claimId':'limits','status':'failed','reason':'Missing seed.',
                'findings':[{'kind':'missing_field','claimId':'limits','path':['executionSpec','seeds'],'reason':'Missing seed.'}]}])}
    capture=Wire();checker=BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=5)
    result=verify_claims([c],[],checker,review_context_version=5)
    assert result['accepted']==[] and result['rejected'][0]['executionState']=='received_invalid'
    assert result['rejected'][0]['rejectionAudit']['bindingState']=='invalid' and len(capture.sent)==1
    old=Wire();old_result=BudgetedSemanticChecker(old,'offline',prospective_review=3,prospective_envelope=4)([c],[])
    assert old_result[0]['reason']=='Missing seed.' and 'rejectionAudit' not in old_result[0]
