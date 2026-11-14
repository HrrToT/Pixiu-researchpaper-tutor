from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.experiment_capacity import enabled, input_limit, reserved_basis_bytes
from services.deep_research.experiment_outline_encoding import encode
from services.deep_research.experiment_planning import prepare_plan, prepare_draft
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_generation_envelope import current as old_record
from test_deep_research_outline_encoding import prompt
from test_deep_research_experiment_planning import Store, response
from test_deep_research_lean_planning import lean_basis


def current():
    r=old_record();r.update(experimentInputContractVersion=1,outputKind='experiment_design')
    return r


def plan(store, invoke=None, text='Exact planning evidence'):
    return prepare_plan(store.value,prompt=text,aliases={'E1':'source1'},
        invoke=invoke or Mock(return_value=response(lean_basis())),parse=json.loads,checkpoint=store.checkpoint)


@pytest.mark.parametrize('version',[None,True,False,0,2,'1'])
def test_strict_version_and_legacy_window(version):
    r=current();r['experimentInputContractVersion']=version
    assert not enabled(r) and input_limit(r)==24000 and reserved_basis_bytes(r)==2500


def test_only_complete_experiment_contract_gets_larger_window():
    r=current();assert enabled(r) and input_limit(r)==32000 and reserved_basis_bytes(r)==4000
    for key,value in [('outputKind','paper_comparison'),('experimentGenerationEnvelopeContractVersion',0),
                      ('experimentOutlineEncodingContractVersion',1),('experimentDraftContractVersion',5)]:
        changed={**r,key:value};assert not enabled(changed) and input_limit(changed)==24000


def sized_body(r,size):
    raw=prompt(prefix='');encoded,audit=encode(r,raw)
    return encode(r,prompt(prefix='x'*(size-len(encoded.encode()))))


@pytest.mark.parametrize('size',[24001,32000,32001])
def test_full_utf8_body_admission_and_persistent_capacity_failure(size):
    store=Store(current());saved=plan(store);body,audit=sized_body(store.value,size)
    if size<=32000:
        request=prepare_draft(store.value,saved,prompt=body,checkpoint=store.checkpoint,outline_encoding_audit=audit)
        assert request['prompt']==body and len(body.encode())==size
    else:
        for _ in range(2):
            with pytest.raises(DeepResearchError) as exc:
                prepare_draft(store.value,store.value['state']['experimentPlanning'],prompt=body,
                              checkpoint=store.checkpoint,outline_encoding_audit=audit)
            assert exc.value.code=='experiment_drafting_input_capacity'
        assert store.value['state']['experimentPlanning']['draftCapacity']['maxInputBytes']==32000


@pytest.mark.parametrize('size',[24001,32000,32001])
def test_planner_window_checked_before_callback(size):
    store=Store(current());invoke=Mock(return_value=response(lean_basis()))
    if size<=32000:
        assert plan(store,invoke,'字'*(size//3)+'x'*(size%3))['status']=='ready'
        invoke.assert_called_once()
    else:
        with pytest.raises(DeepResearchError) as exc:plan(store,invoke,'x'*size)
        assert exc.value.code=='experiment_planning_input_capacity';invoke.assert_not_called()


@pytest.mark.parametrize('pending',[False,True])
def test_old_ready_or_unknown_plan_cannot_change_window(pending):
    store=Store(old_record());invoke=Mock(side_effect=OSError('unknown')) if pending else Mock(return_value=response(lean_basis()))
    if pending:
        with pytest.raises(OSError):plan(store,invoke)
    else:plan(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning']);store.value['experimentInputContractVersion']=1
    store.value['outputKind']='experiment_design';invoke.reset_mock()
    with pytest.raises(DeepResearchError):plan(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen
    with pytest.raises(DeepResearchError):
        body,audit=sized_body(store.value,24001)
        prepare_draft(store.value,frozen,prompt=body,checkpoint=store.checkpoint,outline_encoding_audit=audit)


def test_graph_reserves_max_accepted_plan_and_preserves_complete_input():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_plan_encoding import padded_basis
    from test_deep_research_experiment_representation import wrapped_claims
    store=Store(current());full=padded_basis(3990)
    invoke=Mock(side_effect=[response(full),response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    state=store.value['state'];allocation=state['synthesisPremiseAllocation']
    assert allocation['planningSlotReservedBytes']==4000 and allocation['maxInputBytes']==32000
    assert state['experimentPlanning']['basis']==full and state['experimentPlanning']['experimentInputVersion']==1
    assert state['generationPremiseAllocation']['encodedInputBytes']<=32000
    assert 'each fit4000 UTF-8 bytes' in invoke.call_args_list[0].args[2]
    assert 'in a2500-byte tuple' not in invoke.call_args_list[0].args[2]


def invoker(record,*,reserve=None,cap=32000):
    client=Mock();client.invoke.return_value=LLMResult(content='{}',provider='test',model='offline',usage=LLMUsage(10,2,12))
    reserve=reserve or Mock(return_value=({'callId':'c'},False))
    return TrackedLLMInvoker(client,reserve,Mock(),run_record_fn=lambda _:record,
        experiment_max_input_bytes=cap,verification_max_input_bytes=32000),client,reserve


@pytest.mark.parametrize('node',['plan_experiment','synthesize'])
def test_transport_uses_full_bytes_output_reservation_and_no_retry(node):
    call,client,reserve=invoker(current());text='字'*8001
    call('r',node,text,{'max_tokens':4000})
    assert reserve.call_args.kwargs['budget_delta']=={'modelCalls':1,'tokens':len(text.encode())+1024+4000}
    client.invoke.assert_called_once()
    with pytest.raises(ValueError,match='too large'):call('r',node,'x'*32001,{'max_tokens':4000})
    assert reserve.call_count==1 and client.invoke.call_count==1


def test_window_does_not_increase_total_budget_or_bypass_reservation():
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',99999,100000))
    call,client,_=invoker(current(),reserve=reserve)
    with pytest.raises(BudgetExhaustedError):call('r','synthesize','x'*25000,{'max_tokens':4000})
    reserve.assert_called_once();client.invoke.assert_not_called()


def test_unrelated_nodes_server_ceiling_and_legacy_transport_stay_bounded():
    call,_,_=invoker(current(),cap=28000)
    assert call.prompt_byte_limit('r','synthesize')==28000
    for node in ['extract','repair_claims','final_coverage','plan']:
        assert call.prompt_byte_limit('r',node)==24000
    old,_,_=invoker(old_record());assert old.prompt_byte_limit('r','synthesize')==24000


@pytest.mark.parametrize('cap',[True,0,32001,'32000'])
def test_invalid_server_limit(cap):
    with pytest.raises(ValueError,match='experiment input limit'):invoker(current(),cap=cap)


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_server_owns_immutable_window_version(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'experimentInputContractVersion':replacement,'deferStart':True},start_async=False)
        assert r['experimentInputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda value:{**value,'experimentInputContractVersion':replacement})
    finally:facade.shutdown()
