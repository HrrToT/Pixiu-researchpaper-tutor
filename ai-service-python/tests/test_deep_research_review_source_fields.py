"""Exact field references avoid retyping without granting source permissions."""
from copy import deepcopy
import json

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.factual_decision import decode
from services.deep_research.review_source_fields import GUIDANCE,resolve_response
from services.deep_research.structured_output import normalize
from test_deep_research_factual_decision import checker,evidence,response,target
from test_deep_research_review_reason_parts import opts


def reference_row(supported=True):
    raw=response(supported);raw.pop('reason')
    raw['reasonParts']=[{'text':'The supplied source reports setting 12.',
                        'evidenceId':'E1','path':['quote']}]
    return raw


def run(raw,ev=None,claim=None,**flags):
    calls=[]
    def invoke(**kw):calls.append(kw);return {'content':json.dumps([raw]),'finishReason':'stop'}
    return checker(invoke,**opts(),review_source_fields=True,**flags)([claim or target()],ev or evidence())[0],calls


@pytest.mark.parametrize('supported',[True,False])
def test_reference_expands_only_unchanged_source_and_keeps_semantic_decision(supported):
    raw=reference_row(supported);before=deepcopy(raw)
    result,calls=run(raw)
    assert result['status']==('passed' if supported else 'failed')
    assert result['reviewDiagnosticAudit']['errors']==[]
    assert result['diagnosticFacts'][0]['excerpt']==evidence()[0]['quote']
    assert raw==before and len(calls)==1 and GUIDANCE in calls[0]['prompt']


@pytest.mark.parametrize('path,context',[
    (['sourceContext'],'Method A at setting 12.'),
    (['sourceContext','before'],{'before':'Method A at setting 12.'}),
    (['sourceContext','after'],{'after':'Method A at setting 12.'}),
])
def test_exact_visible_context_types_are_resolved_without_normalization(path,context):
    raw=reference_row();raw['reasonParts'][0]['path']=path
    ev=evidence();ev[0]['sourceContext']=context
    result=resolve_response([raw],[target()],ev,{'E1':'own'})[0]
    expected=context if isinstance(context,str) else context[path[-1]]
    assert result['reasonParts'][0]['excerpt']==expected


@pytest.mark.parametrize('side',['before','after'])
def test_checker_resolves_the_actual_bounded_context_on_its_request(side):
    raw=reference_row();raw['reasonParts'][0]['path']=['sourceContext',side]
    ev=evidence();ev[0]['sourceContext']='Before setting 12. '+ev[0]['quote']+' After setting 12.'
    from services.deep_research.selection import surrounding_context
    expected=surrounding_context(ev[0])[side]
    result,calls=run(raw,ev)
    assert result['diagnosticFacts'][0]['excerpt']==expected
    assert json.dumps(expected,ensure_ascii=False) in calls[0]['prompt']


@pytest.mark.parametrize('mutation',['foreign','sibling','metadata','missing','empty','omitted','wrong_type','bad_path','blank_id','null_id','list_id'])
def test_source_permissions_and_missing_fields_are_never_guessed(mutation):
    raw=reference_row();part=raw['reasonParts'][0];ev=evidence()
    if mutation=='foreign':part['evidenceId']='missing'
    elif mutation=='sibling':part['evidenceId']='sibling';ev.append({'evidenceId':'sibling','quote':'setting 12'})
    elif mutation=='metadata':part['path']=['sourceTitle'];ev[0]['sourceTitle']='setting 12'
    elif mutation=='missing':part['path']=['sourceContext','before']
    elif mutation=='empty':part['path']=['quote'];ev[0]['quote']=' '
    elif mutation=='omitted':part['path']=['sourceContext','before'];ev[0]['sourceContext']={};ev[0]['contextOmitted']=True
    elif mutation=='wrong_type':part['path']=['sourceContext'];ev[0]['sourceContext']={'before':'setting 12'}
    elif mutation=='bad_path':part['path']='quote'
    elif mutation=='blank_id':part['evidenceId']=' '
    elif mutation=='null_id':part['evidenceId']=None
    else:part['evidenceId']=[]
    with pytest.raises(DeepResearchError):run(raw,ev)


def test_explicit_wrong_excerpt_is_not_replaced_by_whole_source_field():
    raw=reference_row();raw['reasonParts'][0]['excerpt']='invented source text'
    result,calls=run(raw)
    assert result['status']=='failed' and len(calls)==1
    assert result['reviewDiagnosticAudit']['errors']==['diagnostic_source_not_bound']


@pytest.mark.parametrize('bound',[True,False])
def test_new_numbers_still_require_same_segment_and_actual_source(bound):
    raw=reference_row();raw['reasonParts'][0]['text']='The correct setting is 0.999.'
    if not bound:raw['reasonParts']=[{'text':'The correct setting is 0.999.'}]
    result,_=run(raw)
    assert result['status']=='failed'
    assert result['reviewDiagnosticAudit']['errors']==['new_diagnostic_numbers_not_bound']


def test_unresolved_reference_cannot_pass_diagnostic_binder_even_after_syntax_decode():
    from services.deep_research.review_diagnostics import bind
    raw=reference_row()
    candidate=decode([raw],diagnostic_facts=True,reason_parts=True,reason_field_references=True)[0]
    result=bind(candidate,target(),evidence(),{'E1':'own'})
    assert result['status']=='failed' and 'invalid_diagnostic_fact' in result['reviewDiagnosticAudit']['errors']


def test_legacy_missing_excerpt_stays_invalid_and_legacy_requests_are_byte_exact():
    raw=reference_row()
    with pytest.raises(DeepResearchError):decode([raw],diagnostic_facts=True,reason_parts=True)
    raw['reasonParts'][0]['excerpt']='setting 12';calls=[]
    def invoke(**kw):calls.append(kw);return {'content':json.dumps([raw])}
    old=checker(invoke,**opts())([target()],evidence());request=calls.pop()
    actual=checker(invoke,**opts(),review_source_fields=False)([target()],evidence())
    assert actual==old and calls==[request] and GUIDANCE not in request['prompt']


def test_singleton_transport_keeps_raw_reference_and_does_not_resolve_or_approve_it():
    raw=reference_row();raw['reasonParts'][0]['evidenceId']='not-provided'
    packet={'content':json.dumps(raw),'finishReason':'stop'}
    flags=dict(factual_singleton=True,factual_diagnostics=True,factual_reason_parts=True)
    result=normalize('verify',packet,**flags,factual_source_fields=True)
    assert result['rawContent']==packet['content'] and json.loads(result['content'])==raw
    assert result['structuredOutput']['receivedShape']=='single_factual_candidate'
    assert normalize('verify',packet,**flags)['content']=='null'
    with pytest.raises(DeepResearchError):run(raw)


@pytest.mark.parametrize('bad',[None,0,1,'1'])
def test_transport_and_decoder_policy_types_are_strict(bad):
    with pytest.raises(ValueError):normalize('verify',{'content':'[]'},factual_source_fields=bad)
    with pytest.raises(ValueError):decode([],reason_field_references=bad)


def test_unknown_or_malformed_claim_identity_cannot_grant_another_targets_source():
    for cid in ('foreign',None,[]):
        raw=reference_row();raw['claimId']=cid
        with pytest.raises(DeepResearchError):resolve_response([raw],[target()],evidence(),{'E1':'own'})


def test_resolution_is_lossless_for_formula_glyphs_and_does_not_mutate_input():
    raw=reference_row();ev=evidence();ev[0]['quote']='ˆmₜ←mₜ/(1−(1−β₁)ᵗ)\n  exact\tﬁeld'
    before=deepcopy((raw,ev))
    resolved=resolve_response([raw],[target()],ev,{'E1':'own'})
    assert resolved[0]['reasonParts'][0]['excerpt']==ev[0]['quote']
    assert (raw,ev)==before


def test_fitted_out_context_is_not_restored_from_full_original_evidence():
    from services.deep_research.prompt_budget import fit_evidence_prompt
    ev=evidence();ev[0]['sourceContext']={'before':'hidden formula '*200}
    _,visible=fit_evidence_prompt(ev,lambda rows:json.dumps(rows),max_bytes=250)
    assert visible[0]['contextOmitted'] is True
    raw=reference_row();raw['reasonParts'][0]['path']=['sourceContext','before']
    with pytest.raises(DeepResearchError):resolve_response([raw],[target()],visible,{'E1':'own'})


def test_root_flag_is_server_owned_immutable_and_does_not_migrate_old_runs(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    key='reviewSourceFieldReferenceContractVersion'
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',key:False},start_async=False)
        assert type(row[key]) is int and row[key]==1
        assert facade._make_semantic_checker(row['runId'])._review_source_fields() is True
        old=deepcopy(row);old.pop(key);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        assert facade._make_semantic_checker('old')._review_source_fields() is False
        for rid in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,key:2})
    finally:facade.shutdown()


@pytest.mark.parametrize('shape',['singleton','array','items'])
def test_actual_tracked_transport_journals_raw_reference_and_checker_resolves_it(tmp_path,shape):
    from unittest.mock import Mock
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.repository import DeepResearchRepository
    from test_deep_research_structured_output import tracked
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','structuredOutputContractVersion':15,
        'factualEnvelopeContractVersion':2,'factualDecisionContractVersion':2,
        'reviewDiagnosticContractVersion':2,'reviewReasonPartsContractVersion':1,
        'reviewSourceFieldReferenceContractVersion':1})
    repo.begin_execution('r')
    row=reference_row();wire=row if shape=='singleton' else [row] if shape=='array' else {'items':[row]}
    raw=json.dumps(wire);client=Mock()
    client.invoke.return_value=LLMResult(content=raw,provider='fixture',model='fixture',
        usage=LLMUsage(input_tokens=5,output_tokens=2,total_tokens=7),finish_reason='stop')
    result=checker(tracked(repo,client),**opts(),review_source_fields=True,
                   singleton_factual_response=True)([target()],evidence())[0]
    assert result['status']=='passed' and client.invoke.call_count==1
    stored=repo.list_calls('r')[0]['result'];assert stored['rawContent']==raw
    parsed=json.loads(stored['content']);parsed=parsed[0] if isinstance(parsed,list) else parsed
    assert parsed==row and 'excerpt' not in parsed['reasonParts'][0]
    assert result['diagnosticFacts'][0]['excerpt']==evidence()[0]['quote']


def test_received_invalid_reference_is_not_retried_or_reclassified_as_unsupported():
    from services.deep_research.review_response_failure import invalid
    raw=reference_row();raw['reasonParts'][0]['evidenceId']='foreign'
    result,calls=run(raw,known_single_review_failure=True,isolate_factual_claims=True)
    assert len(calls)==1 and result['status']=='failed'
    assert result['executionState']=='received_invalid' and invalid(result['reviewResponseAudit'])
