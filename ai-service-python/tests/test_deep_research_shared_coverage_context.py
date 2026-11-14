from copy import deepcopy
from unittest.mock import Mock,patch
import json
import pytest
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables


def inputs():
    plan=[{'obligations':[{'obligationId':'o','question':'Explain both constraints.'}]}]
    claims=[{'claimId':'c'+str(i),'text':'Supported constraint '+str(i),'kind':'reported','evidenceRefs':['e'+str(i)],'obligationIds':['o']} for i in (1,2)]
    context='Complete original quoted mechanism. '+'x'*11000
    rows=[{'evidenceId':'e'+str(i),'quote':context,
        'sourceContext':context,'sourceWorkId':'p'+str(i),'sourceVersionId':'v','conditions':{'$':i,'~':'literal'}} for i in (1,2)]
    return plan,claims,rows


def test_complete_context_fits_without_dropping_citations_or_raising_byte_limit():
    plan,claims,rows=inputs();before=deepcopy((plan,claims,rows))
    old=Mock();legacy=audit_final_answer('r','Explain both.',plan,claims,rows,old,json.loads,diagnostics=True)
    assert legacy['status']=='budget_exhausted';old.assert_not_called()
    reference=Mock(return_value={'content':'[]'})
    with patch('services.deep_research.final_coverage.coverage_prompt_byte_limit',return_value=1000000):
        audit_final_answer('r','Explain both.',plan,claims,rows,reference,json.loads,diagnostics=True)
    original_wire=reference.call_args.args[2].split('Available evidence for detecting omitted conditions: ',1)[1]
    literal_rows,_=json.JSONDecoder().raw_decode(original_wire)
    invoke=Mock(return_value={'content':'[]','finishReason':'stop'})
    result=audit_final_answer('r','Explain both.',plan,claims,rows,invoke,json.loads,
        diagnostics=True,shared_evidence_context=True)
    invoke.assert_called_once();text=invoke.call_args.args[2]
    assert len(text.encode())<=24000 and result['coverageEvidenceTransportVersion']==1
    payload=text.split('Available evidence for detecting omitted conditions: ',1)[1]
    wire,end=json.JSONDecoder().raw_decode(payload)
    decoded=untables(unpack(wire))
    assert len(decoded)==2 and {r['quote'] for r in decoded}=={r['quote'] for r in rows}
    assert decoded==literal_rows
    assert {r['source'] for r in decoded}=={'p1','p2'}
    assert {r['conditions']['$'] for r in decoded}=={1,2}
    assert all(r['conditions']['~']=='literal' for r in decoded)
    assert result['gaps'] and (plan,claims,rows)==before


def test_uncodable_overcapacity_still_has_zero_provider_calls():
    plan,claims,rows=inputs()
    rows[0]['sourceContext']=rows[0]['quote']='x'*50000
    rows[1]['sourceContext']=rows[1]['quote']='y'*50000
    invoke=Mock()
    result=audit_final_answer('r','Explain both.',plan,claims,rows,invoke,json.loads,
        diagnostics=True,shared_evidence_context=True)
    assert result['status']=='budget_exhausted';invoke.assert_not_called()


@pytest.mark.parametrize('flag',[True,1,'yes'])
def test_shared_transport_requires_explicit_complete_context_admission(flag):
    with pytest.raises(ValueError):
        audit_final_answer('r','q',[],[],[],Mock(),json.loads,shared_evidence_context=flag)


@pytest.mark.parametrize('fixed_checks',[False,True])
def test_new_graph_policy_scopes_catalog_only_when_fixed_check_contract_is_active(monkeypatch,fixed_checks):
    from services.deep_research.graph import make_verify_node
    from test_deep_research_final_coverage import PLAN,CLAIMS
    record={'question':'Explain the conditions.','coverageDiagnosticsContractVersion':4,
        'state':{'plan':PLAN,'reportBody':{'claims':CLAIMS},'evidence':[],
                 'outputKind':'claim_verification','gaps':[]}}
    if fixed_checks:record['requestCoverageContractVersion']=3
    def update(_id,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    capture=Mock(return_value={'status':'checked','gaps':[]})
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',capture)
    make_verify_node(lambda *a:{'accepted':CLAIMS,'rejected':[]},None,update,Mock())({'run_id':'r'})
    assert capture.call_args.kwargs.get('scoped_catalog') is (True if fixed_checks else None)
    assert capture.call_args.kwargs['diagnostics'] is True
    assert capture.call_args.kwargs['shared_evidence_context'] is True
