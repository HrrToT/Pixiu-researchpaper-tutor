"""Malformed audits remain unresolved, but expose safe actionable locations."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.request_coverage import normalize
from services.deep_research.final_coverage import audit_final_answer


FIXED = [{'obligationId':'o','question':'Explain the mechanism','purpose':'answer_requirement',
          'checks':[{'checkId':'c','requirement':'Explain the mechanism','processRequired':True}]}]
ROW = {'obligationId':'o','checks':[{'checkId':'c','status':'missing','bindings':[],
                                   'reason':'No mechanism in the accepted answer.'}]}


def test_missing_process_links_location_does_not_accept_or_rewrite():
    raw = [deepcopy(ROW)]; before = deepcopy(raw); errors = []
    assert normalize(raw,FIXED,process_explanations=True,response_errors=errors) is None
    assert normalize(raw,FIXED,process_explanations=True) is None
    assert raw == before
    assert errors == [{'code':'invalid_check_fields','obligationId':'o','checkId':'c',
                       'missingFields':['processLinks']}]


@pytest.mark.parametrize('mutation,code',[
    ('root','response_not_array'),('obligation','obligation_identity_mismatch'),
    ('duplicate','obligation_identity_mismatch'),('row','invalid_obligation_shape'),
    ('check','check_identity_mismatch'),('status','invalid_check_value'),
    ('binding','invalid_check_value'),('extra','invalid_check_fields')])
def test_failure_locations_preserve_previous_fail_closed_decision(mutation,code):
    raw = [deepcopy(ROW)]; raw[0]['checks'][0]['processLinks'] = []
    if mutation=='root':raw={}
    elif mutation=='obligation':raw[0]['obligationId']='foreign-private-text'
    elif mutation=='duplicate':raw.append(deepcopy(raw[0]))
    elif mutation=='row':raw[0]['private-source-content']='sensitive'
    elif mutation=='check':raw[0]['checks'][0]['checkId']='foreign-private-text'
    elif mutation=='status':raw[0]['checks'][0]['status']='approved'
    elif mutation=='binding':raw[0]['checks'][0]['bindings']=[{'claimId':'unknown'}]
    elif mutation=='extra':raw[0]['checks'][0]['private-source-content']='sensitive'
    errors=[]
    assert normalize(raw,FIXED,process_explanations=True,response_errors=errors) is None
    assert normalize(raw,FIXED,process_explanations=True) is None
    assert errors[0]['code']==code
    assert 'private' not in json.dumps(errors) and 'sensitive' not in json.dumps(errors)


def test_valid_missing_decision_stays_missing_without_synthetic_support():
    raw=[deepcopy(ROW)];raw[0]['checks'][0]['processLinks']=[]; errors=[]
    result=normalize(raw,FIXED,process_explanations=True,response_errors=errors)
    assert result==normalize(raw,FIXED,process_explanations=True)
    assert result[0]['status']=='missing' and errors==[]


def test_final_audit_preserves_failure_location_without_additional_call():
    plan=[{'obligations':[{'obligationId':'o','question':'Explain the mechanism',
        'completionCriteria':[{'criterionId':'mechanism','requirement':'Explain the mechanism',
                               'responseType':'limitation'}]}]}]
    claims=[{'claimId':'a','kind':'reported','text':'A limited result is available.',
             'evidenceRefs':[],'conditions':{}}]
    rows=[{'obligationId':oid,'checks':[{'checkId':cid,'status':'missing','bindings':[],
        'reason':'No explanation.'}]} for oid,cid in [('o','criterion:mechanism'),('answer_scope','request')]]
    invoke=Mock(return_value={'content':json.dumps(rows)})
    result=audit_final_answer('r','Explain the mechanism',plan,claims,[],invoke,json.loads,
        diagnostics=True,request_contract=3,consolidated_instructions=True,literal_limits=True)
    assert result['status']=='invalid_response' and result['verdicts']==[]
    assert result['requestResponseErrors']==[{'code':'invalid_check_fields','obligationId':'o',
        'checkId':'criterion:mechanism','missingFields':['limitSpans']}]
    assert invoke.call_count==1
    assert len(result['gaps'])==2
    opted=audit_final_answer('r','Explain the mechanism',plan,claims,[],invoke,json.loads,
        diagnostics=True,request_contract=3,consolidated_instructions=True,literal_limits=True,
        empty_missing_limits=True)
    assert opted['status']=='checked' and len(opted['gaps'])==2
    assert all(v['status']=='missing' for v in opted['verdicts'])
    assert 'requestResponseErrors' not in opted and invoke.call_count==2


def test_opt_in_empty_locator_preserves_explicit_missing_and_does_not_mutate_raw():
    raw=[deepcopy(ROW)];raw[0]['checks'][0]['checkId']='c'
    fixed=deepcopy(FIXED);fixed[0]['checks'][0].pop('processRequired')
    fixed[0]['checks'][0]['responseType']='limitation';before=deepcopy(raw)
    errors=[]
    result=normalize(raw,fixed,literal_limits=True,empty_missing_limits=True,response_errors=errors)
    assert result[0]['status']=='missing' and result[0]['limitAudits'][0]['spans']==[]
    assert errors==[] and raw==before
    assert normalize(raw,fixed,literal_limits=True) is None


@pytest.mark.parametrize('status,bindings,extra',[
    ('covered',[],{}),('partial',[],{}),('missing',[{'claimId':'x','field':'text'}],{}),
    ('missing',[],{'unexpected':'value'})])
def test_negative_locator_normalization_never_fills_positive_or_invalid_decisions(status,bindings,extra):
    fixed=deepcopy(FIXED);fixed[0]['checks'][0].pop('processRequired')
    fixed[0]['checks'][0]['responseType']='limitation'
    raw=[deepcopy(ROW)];raw[0]['checks'][0].update(status=status,bindings=bindings,**extra)
    assert normalize(raw,fixed,literal_limits=True,empty_missing_limits=True) is None


def test_explicit_bad_locator_is_never_replaced_by_empty_locator():
    fixed=deepcopy(FIXED);fixed[0]['checks'][0].pop('processRequired')
    fixed[0]['checks'][0]['responseType']='limitation'
    raw=[deepcopy(ROW)];raw[0]['checks'][0]['limitSpans']=None
    expected=normalize(raw,fixed,literal_limits=True)
    actual=normalize(raw,fixed,literal_limits=True,empty_missing_limits=True)
    assert actual==expected and actual[0]['status']=='missing'
    assert actual[0]['limitAudits'][0]['spans'] is None
    assert actual[0]['limitAudits'][0]['errors']==['invalid_limit_spans']
