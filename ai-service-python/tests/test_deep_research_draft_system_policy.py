from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.structured_output import messages,messages_for_record
from services.deep_research.draft_system_policy import DRAFT_NODES,OLD,NEW
from services.deep_research.contracts import DeepResearchError


def record(flag=1):
    return {'structuredOutputContractVersion':15,'draftSystemContractVersion':flag,
            'state':{'outputKind':'claim_verification'},'materials':[],
            'budget':{'maxWallClockSeconds':360}}


@pytest.mark.parametrize('node',sorted(DRAFT_NODES))
def test_real_high_priority_clause_matches_allowed_source_and_kind_permissions(node):
    r=record();before=deepcopy(r);out=messages_for_record(r,node,'server schema and allowed targets')
    legacy=messages(node,'server schema and allowed targets',15)
    assert out[1]==legacy[1] and out[0]['content']==legacy[0]['content'].replace(OLD,NEW,1)
    assert OLD not in out[0]['content'] and NEW in out[0]['content']
    assert len(out[0]['content'].encode('utf8'))+128<=1024
    assert 'Private drafting fields are unverified' in out[0]['content'] and r==before


@pytest.mark.parametrize('version',range(1,16))
def test_frozen_legacy_runs_keep_their_exact_messages_for_all_roles(version):
    for node in (*sorted(DRAFT_NODES),'plan','extract','verify','verify_repair','verify_answer_coverage','plan_experiment'):
        r={'structuredOutputContractVersion':version,'state':{'outputKind':'claim_verification'}}
        assert messages_for_record(r,node,'same input')==messages(node,'same input',version)


@pytest.mark.parametrize('flag',[None,True,False,0,'1',2])
def test_policy_requires_a_strict_server_version(flag):
    assert messages_for_record(record(flag),'repair_claims','input')==messages('repair_claims','input',15)


@pytest.mark.parametrize('node',[*sorted(DRAFT_NODES),'verify','verify_repair','verify_answer_coverage','plan_experiment'])
def test_experiment_and_independent_review_policies_are_unchanged(node):
    r=record();r['state']['outputKind']='experiment_design'
    assert messages_for_record(r,node,'input')==messages(node,'input',15,prospective=True)
    if node not in DRAFT_NODES:
        assert messages_for_record(record(),node,'input')==messages(node,'input',15)


def test_tracked_request_fingerprints_high_priority_policy_and_reuses_exact_settled_call():
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.provider import LLMResult,LLMUsage
    provider=Mock();provider.invoke.return_value=LLMResult('fixture','fixture','{"items":[]}',LLMUsage(1,1,2))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'t'},False));complete=Mock()
    r=record();invoke=TrackedLLMInvoker(provider,reserve,complete,run_record_fn=lambda _:r)
    invoke('r','repair_claims','body',{'max_tokens':2000},use_reserve=True)
    wire=provider.invoke.call_args.args[0]
    assert wire.messages==messages_for_record(r,'repair_claims','body') and NEW in wire.messages[0]['content']
    fingerprint=reserve.call_args.kwargs['args_digest'];delta=deepcopy(reserve.call_args.kwargs['budget_delta'])
    reserve.return_value=({'callId':'c','result':{'content':'[]'}},True)
    assert invoke('r','repair_claims','body',{'max_tokens':2000},use_reserve=True)['content']=='[]'
    assert provider.invoke.call_count==1 and reserve.call_args.kwargs['args_digest']==fingerprint
    r.pop('draftSystemContractVersion');reserve.return_value=({'callId':'old','reservationToken':'old'},False)
    invoke('r','repair_claims','body',{'max_tokens':2000},use_reserve=True)
    assert reserve.call_args.kwargs['args_digest']!=fingerprint
    assert reserve.call_args.kwargs['budget_delta']==delta


def test_scoped_client_rejects_stale_system_message_before_provider_send():
    from services.deep_research.runtime import ScopedModelClient
    from services.deep_research.planning_transport import options_for_record
    from llm.provider import LLMRequest
    r=record();repo=Mock();repo.require_run.return_value=r;provider=Mock()
    client=ScopedModelClient(repo,lambda *_:True,lambda:provider).for_run('r').for_node('repair_claims')
    options=options_for_record(r,'repair_claims',{})
    with pytest.raises(DeepResearchError) as error:
        client.invoke(LLMRequest(prompt='body',messages=messages('repair_claims','body',15),extra_body=options))
    assert error.value.code=='invalid_model_options';provider.invoke.assert_not_called()
    client.invoke(LLMRequest(prompt='body',messages=messages_for_record(r,'repair_claims','body'),extra_body=options))
    assert NEW in provider.invoke.call_args.args[0].messages[0]['content']


@pytest.mark.parametrize('replacement',[None,True,False,0,'1',2])
def test_factory_owns_immutable_policy_and_does_not_migrate_old_record(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'核查',
            'deferStart':True,'draftSystemContractVersion':replacement},start_async=False)
        assert type(r['draftSystemContractVersion']) is int and r['draftSystemContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'draftSystemContractVersion':replacement})
        legacy=deepcopy(r);legacy.update(runId='old',idempotencyKey='old');legacy.pop('draftSystemContractVersion')
        repo.create_run(legacy);before=repo.require_run('old')
        facade.create({'workspaceTaskId':'t','operationKey':'another','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'draftSystemContractVersion':1})
    finally:facade.shutdown()
