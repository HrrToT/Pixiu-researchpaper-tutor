"""Versioned native-envelope fields must agree with the independent checker."""
import json
from unittest.mock import Mock
import pytest
from llm.provider import LLMResult,LLMUsage
from services.deep_research.structured_output import normalize
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_decision import response,target,evidence,checker
from test_deep_research_structured_output import tracked


def setup(tmp_path,version=2,diagnostics=2):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','structuredOutputContractVersion':15,
        'factualEnvelopeContractVersion':version,'factualDecisionContractVersion':2,
        'reviewDiagnosticContractVersion':diagnostics,'reportingOwnershipContractVersion':1})
    repo.begin_execution('r');return repo


def client_for(row):
    client=Mock();client.invoke.return_value=LLMResult(content=json.dumps(row),provider='fixture',model='fixture',
        usage=LLMUsage(input_tokens=5,output_tokens=2,total_tokens=7),finish_reason='stop')
    return client

@pytest.mark.parametrize('supported',[True,False])
def test_actual_tracked_transport_keeps_diagnostics_and_explicit_decision(tmp_path,supported):
    repo=setup(tmp_path);row={**response(supported),'diagnosticFacts':[]};client=client_for(row)
    invoke=tracked(repo,client)
    result=checker(invoke,singleton_factual_response=True,review_diagnostic_bindings=True,integrated_diagnostic_schema=True)([target()],evidence())
    assert result[0]['status']==('passed' if supported else 'failed')
    saved=repo.list_calls('r')[0]['result'];assert json.loads(saved['content'])==row
    assert saved['rawContent']==json.dumps(row) and saved['structuredOutput']['receivedShape']=='single_factual_candidate'
    reopened=DeepResearchRepository(repo.db_path);reopened.initialize()
    assert checker(tracked(reopened,client),singleton_factual_response=True,review_diagnostic_bindings=True,integrated_diagnostic_schema=True)([target()],evidence())==result
    assert client.invoke.call_count==1
    assert repo.require_run('r')['budget']['tokens']==7

@pytest.mark.parametrize('version',[1,None,True])
def test_legacy_versions_do_not_opt_into_diagnostic_singleton_fields(tmp_path,version):
    repo=setup(tmp_path,version);client=client_for({**response(),'diagnosticFacts':[]})
    result=tracked(repo,client)('r','verify','frozen request',{'max_tokens':100})
    assert result['content']=='null' and client.invoke.call_count==1

@pytest.mark.parametrize('mutation',['wrong_target','foreign_premise','missing_diagnostics','invented_excerpt','conflicting_status'])
def test_scientific_gates_still_reject_invalid_content(tmp_path,mutation):
    row={**response(),'diagnosticFacts':[]}
    if mutation=='wrong_target':row['claimId']='other'
    elif mutation=='foreign_premise':row['scopeAudit']['premises'][0]['evidenceId']='foreign'
    elif mutation=='missing_diagnostics':row.pop('diagnosticFacts')
    elif mutation=='invented_excerpt':
        row['reason']='An invented fact.'
        row['diagnosticFacts']=[{'statement':'An invented fact.','evidenceId':'E1','path':['quote'],'excerpt':'absent source text'}]
    else:row['status']='passed'
    client=client_for(row);repo=setup(tmp_path)
    check=checker(tracked(repo,client),singleton_factual_response=True,review_diagnostic_bindings=True,integrated_diagnostic_schema=True)
    try:result=check([target()],evidence())
    except DeepResearchError:pass
    else:assert result[0]['status']=='failed'
    assert client.invoke.call_count==1


def test_ownership_field_requires_opt_in_and_raw_response_never_modified():
    row={**response(),'diagnosticFacts':[],'reportingOwnershipAudit':[]}
    raw={'content':json.dumps(row),'finishReason':'stop'}
    assert normalize('verify',raw,factual_singleton=True,factual_diagnostics=True)['content']=='null'
    result=normalize('verify',raw,factual_singleton=True,factual_diagnostics=True,factual_ownership=True)
    assert json.loads(result['content'])==row and result['rawContent']==raw['content']
    assert normalize('verify',raw)['content']=='null'

