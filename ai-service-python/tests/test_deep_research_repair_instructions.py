from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.repair_instructions import enabled
from test_deep_research_authored_body import prose,decode,evidence,options


def fixture():
    original=decode(prose('c'))
    report={'claims':[original]}
    verification={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete','missingQuestions':['Explain the operation.']}]}
    opts={**options(),'required_scope_ids':[],'target_goals':5,'verbatim_repair':True}
    return report,verification,evidence(),opts


def test_actual_preparation_preserves_source_permissions_and_goals_with_one_instruction_set():
    report,verification,ev,opts=fixture();snapshot=deepcopy((report,verification,ev,opts))
    old=_prepare_repair(report,verification,ev,'Explain the operation.',max_prompt_bytes=32000,**opts)
    new=_prepare_repair(report,verification,ev,'Explain the operation.',consolidated_instructions=True,**opts)
    for key in ('originals','aliases','allowed','repairPremiseAudit','repairRemovalContractVersion','scopeExpressionContractVersion'):
        assert new[key]==old[key]
    prompt=new['prompt']; packet=prompt.split('Exact repair inputs (goals and metadata, not paper facts):\n')[1].split('\nAllowed evidence IDs')[0]
    data=json.loads(packet)
    assert data['goalsByTarget']=={'c':['o']}
    assert data['targets'][0]['claim']['claimId']=='c'
    assert data['targets'][0]['checks']['reason']=='answer_incomplete'
    assert data['requiredBoundaryIds']==[] and data['sourceRegistry']['sources']
    assert data['outputRowSchema']['body'] and 'discardedDraftSpans' in data['outputRowSchema']
    assert all(e['quote'] in prompt for e in ev if e['evidenceId'] in new['allowed']['c'])
    assert len(prompt.encode())<len(old['prompt'].encode())
    assert new['repairInstructionsContractVersion']==1
    assert snapshot==(report,verification,ev,opts)


def test_response_is_still_unverified_and_cached_batches_cannot_switch_instruction_policy():
    report,verification,ev,opts=fixture(); raw=prose('c');raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    states=[]; invoke=Mock(return_value={'content':json.dumps([raw])})
    args=(report,verification,ev,'Explain the operation.',invoke,json.loads)
    result=repair_rejected(*args,consolidated_instructions=True,checkpoint=states.append,**opts)
    assert result and invoke.call_count==1
    invoke.reset_mock()
    assert repair_rejected(*args,consolidated_instructions=True,batch_state=states[-1],**opts)==result
    invoke.assert_not_called()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):repair_rejected(*args,batch_state=states[-1],**opts)
    invoke.assert_not_called()
    from services.deep_research.verification import verify_claims
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Unsupported fixture'}])
    assert not verify_claims(result,ev,checker)['accepted']


@pytest.mark.parametrize('mutation',['retained_deletion','wrong_body','foreign_citation'])
def test_new_instructions_do_not_accept_malformed_edits_or_foreign_evidence(mutation):
    report,verification,ev,opts=fixture(); raw=prose('c');raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    if mutation=='retained_deletion':raw['discardedDraftSpans']=['照片']
    if mutation=='wrong_body':raw['text']='top level forbidden'
    if mutation=='foreign_citation':raw['evidenceRefs']=['foreign']
    invoke=Mock(return_value={'content':json.dumps([raw])})
    assert repair_rejected(report,verification,ev,'Explain the operation.',invoke,json.loads,consolidated_instructions=True,**opts)==[]
    invoke.assert_called_once()


@pytest.mark.parametrize('flag',[None,True,False,0,2,1.0,'1'])
def test_only_exact_frozen_server_profile_enables_new_instructions(flag):
    r={'repairInstructionsContractVersion':flag,'verbatimRepairContractVersion':1,
       'factualRepairGoalContractVersion':5,'authoredBodyContractVersion':1,
       'scopeExpressionContractVersion':5,'factualPromptContractVersion':3,
       'factRedraftContractVersion':3,'factualRepairPromptContractVersion':3,
       'state':{'outputKind':'paper_comparison'}}
    assert not enabled(r)
    r['repairInstructionsContractVersion']=1;assert enabled(r)
    r['verbatimRepairContractVersion']=0;assert not enabled(r)


@pytest.mark.parametrize('bad',[1,None,'1'])
def test_direct_non_boolean_policy_is_rejected_before_dispatch(bad):
    report,verification,ev,opts=fixture();invoke=Mock()
    with pytest.raises(ValueError):repair_rejected(report,verification,ev,'Explain',invoke,json.loads,consolidated_instructions=bad,**opts)
    invoke.assert_not_called()


def test_unfit_required_quotes_are_not_truncated_or_sent():
    report,verification,ev,opts=fixture()
    ev[0]['quote']='source '+('long original passage '*2000)
    from services.deep_research.contracts import BudgetExhaustedError
    invoke=Mock()
    with pytest.raises(BudgetExhaustedError):
        repair_rejected(report,verification,ev,'Explain',invoke,json.loads,
            consolidated_instructions=True,verified_target_ids=['c'],**opts)
    invoke.assert_not_called()


def test_boundary_ids_and_typed_table_schema_are_preserved_in_exact_input_packet():
    from services.deep_research.repair_instructions import render
    data=dict(question='Compare A and B.',length_contract='',requirements=[{'obligationId':'o'}],
        source_context={'sources':{'P1':{'sourceVersionId':'v1'}}},targets=[{'claimId':'c'}],
        checks={'c':{'reason':'semantic_unresolved'}},questions={},permissions_marker='permissions',
        evidence_marker='evidence',schema={'tableBindings':[]},goals={'c':['o']},hints={'c':'untrusted'},
        intentions={'c':{'scopeDecision':'bounded_inference'}},inference_ids=['c'],required_scope_ids=['c'],has_tables=True)
    before=deepcopy(data);prompt=render(**data)
    packet=json.loads(prompt.split('Exact repair inputs (goals and metadata, not paper facts):\n')[1].split('\nAllowed evidence IDs')[0])
    assert packet['requiredBoundaryIds']==['c'] and packet['reportedToInferenceIds']==['c']
    assert packet['sourceRegistry']==data['source_context'] and packet['outputRowSchema']==data['schema']
    assert 'original rowNumber' in prompt and 'comparison_evidence' in prompt and 'all|exists' in prompt
    assert data==before


def test_policy_server_owned_immutable_and_cannot_be_added_to_legacy_run(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,
            'repairInstructionsContractVersion':False},start_async=False)
        assert type(r['repairInstructionsContractVersion']) is int and r['repairInstructionsContractVersion']==1
        ready=deepcopy(r);ready['state']['outputKind']='claim_verification';assert enabled(ready)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'repairInstructionsContractVersion':False})
        old=deepcopy(r);old.pop('repairInstructionsContractVersion');old.update(runId='legacy',idempotencyKey='old')
        repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'repairInstructionsContractVersion':1})
        assert not enabled(repo.require_run('legacy'))
    finally:facade.shutdown()
