from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult,LLMUsage
from services.deep_research.contracts import DeepResearchError
from services.deep_research.structured_output import normalize
from test_deep_research_factual_decision import response,target,evidence,checker
from test_deep_research_structured_output import tracked
from services.deep_research.repository import DeepResearchRepository


def repository(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','structuredOutputContractVersion':15,
                     'factualEnvelopeContractVersion':1,'factualDecisionContractVersion':2,
                     'externalReadingContractVersion':1,'sourceGapClosureContractVersion':1})
    repo.begin_execution('r');return repo


@pytest.mark.parametrize('supported',[False,True])
def test_actual_tracked_native_transport_preserves_explicit_decision_for_exact_checker(tmp_path,supported):
    repo=repository(tmp_path)
    raw=json.dumps(response(supported));client=Mock()
    client.invoke.return_value=LLMResult(content=raw,provider='fixture',model='fixture',usage=LLMUsage(input_tokens=5,output_tokens=2,total_tokens=7),finish_reason='stop')
    invoke=tracked(repo,client)
    result=checker(invoke,singleton_factual_response=True)([target()],evidence())
    assert result[0]['status']==('passed' if supported else 'failed')
    assert client.invoke.call_count==1
    stored=repo.list_calls('r')[0]['result']
    assert stored['rawContent']==raw and json.loads(stored['content'])==response(supported)
    assert stored['structuredOutput']['receivedShape']=='single_factual_candidate'


@pytest.mark.parametrize('change',['wrong_target','foreign_premise','multiple_targets'])
def test_native_transport_never_supplies_target_identity_or_evidence_permission(tmp_path,change):
    repo=repository(tmp_path)
    row=response();claims=[target()]
    if change=='wrong_target':row['claimId']='foreign'
    elif change=='foreign_premise':row['scopeAudit']['premises'][0]['evidenceId']='foreign'
    else:claims.append({**target(),'claimId':'other'})
    client=Mock();client.invoke.return_value=LLMResult(content=json.dumps(row),provider='fixture',model='fixture',usage=LLMUsage(input_tokens=5,output_tokens=2,total_tokens=7),finish_reason='stop')
    check=checker(tracked(repo,client),singleton_factual_response=True)
    if change=='foreign_premise':assert check(claims,evidence())[0]['status']=='failed'
    else:
        with pytest.raises(DeepResearchError):check(claims,evidence())
    assert client.invoke.call_count==1


@pytest.mark.parametrize('change',['legacy_status','missing_scope','numeric_boolean','extra_wrapper','truncated','duplicate_key'])
def test_envelope_compatibility_does_not_repair_scientific_fields_or_truncation(change):
    row=response();finish='stop'
    if change=='legacy_status':row['status']='passed'
    elif change=='missing_scope':row.pop('scopeAudit')
    elif change=='numeric_boolean':row['scopeAudit']['supported']=1
    elif change=='extra_wrapper':row={'items':row}
    elif change=='truncated':finish='length'
    raw=json.dumps(row)
    if change=='duplicate_key':raw=raw.replace('"claimId": "c"','"claimId": "c", "claimId": "other"')
    source={'content':raw,'finishReason':finish};before=deepcopy(source)
    assert normalize('verify',source,factual_singleton=True)['content']=='null'
    assert source==before


@pytest.mark.parametrize('node',['verify','verify_repair','verify_design_science','verify_advice','plan'])
def test_opt_in_is_restricted_to_factual_checker_nodes_and_legacy_stays_unchanged(node):
    source={'content':json.dumps(response()),'finishReason':'stop'}
    assert normalize(node,source)['content']=='null'
    actual=normalize(node,source,factual_singleton=True)
    assert (actual['content']!='null') is (node in {'verify','verify_repair'})


@pytest.mark.parametrize('field',['externalReadingContractVersion','sourceGapClosureContractVersion','factualEnvelopeContractVersion'])
@pytest.mark.parametrize('value',[True,2,None])
def test_new_policy_fields_are_frozen_with_strict_types_for_all_saved_runs(tmp_path,field,value):
    repo=repository(tmp_path);before=repo.require_run('r')
    with pytest.raises(ValueError,match='Immutable run field changed'):
        repo.update_run('r',lambda r:{**r,field:value})
    assert repo.require_run('r')==before


def test_legacy_record_cannot_opt_into_new_decoding_after_an_unknown_call(tmp_path):
    repo=DeepResearchRepository(tmp_path/'legacy.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t'});before=repo.require_run('r')
    with pytest.raises(ValueError,match='Immutable run field changed'):
        repo.update_run('r',lambda r:{**r,'factualEnvelopeContractVersion':1})
    assert repo.require_run('r')==before
