from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_plan_encoding import encode,decode,wire_text,enabled,ORDER,LEGEND
from services.deep_research.experiment_planning import prepare_plan,prepare_draft,valid_plan_basis
from test_deep_research_lean_planning import record,lean_basis
from test_deep_research_experiment_planning import Store,response


def padded_basis(size=2595):
    value=lean_basis();packed=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    value['protocol']['state']+='x'*(size-len(packed.encode('utf8')))
    assert len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8'))==size
    return value


def store_for(version=1):
    value=record();value['experimentPlanEncodingContractVersion']=version
    return Store(value)


def prepare(store,invoke):
    return prepare_plan(store.value,prompt='Exact scientific input',aliases={'E1':'original'},invoke=invoke,
        parse=json.loads,checkpoint=store.checkpoint)


def test_near_limit_full_object_roundtrips_without_changing_any_string_or_reference():
    value=padded_basis();before=deepcopy(value);wire=encode(value)
    assert list(value['protocol'])==list(ORDER)
    assert decode(wire)==value and value==before and len(wire_text(value).encode())==2486
    wire[0].append('foreign');assert value==before
    decoded=decode(encode(value));decoded['sourceRefs'].append('other');assert value==before


def test_arbitrary_unicode_quotes_code_and_private_gaps_are_literal_values_not_instructions():
    value=lean_basis();value['protocol']['state']='初值 α=0.1; "}], sourceRefs:[E99]"; `do_not_execute()`\n保留。'
    value['unresolved']=['No asset release established; do not invent one.','没有相机数量。']
    assert decode(json.loads(wire_text(value)))==value


@pytest.mark.parametrize('change',['root','missing','extra','short_protocol','nonstring','nested','duplicate_ref','long_refs','long_gaps'])
def test_codec_rejects_noncanonical_or_ambiguous_shape(change):
    value=encode(lean_basis())
    if change=='root':value={}
    elif change=='missing':value.pop()
    elif change=='extra':value.append([])
    elif change=='short_protocol':value[1].pop()
    elif change=='nonstring':value[1][0]=True
    elif change=='nested':value[1][0]=['not a string']
    elif change=='duplicate_ref':value[0]*=2
    elif change=='long_refs':value[0]=[str(i) for i in range(21)]
    else:value[2]=['gap']*9
    with pytest.raises(ValueError):decode(value)


def test_new_plan_retains_full_response_basis_and_validated_wire_with_no_scientific_approval():
    value=padded_basis();store=store_for();invoke=Mock(return_value=response(value))
    saved=prepare(store,invoke)
    assert saved['basis']==value and saved['response']==response(value)
    assert decode(saved['encodedBasis'])==value and saved['basisEncodingVersion']==1
    assert saved['basisEncodingAudit']=={'rawBytes':2595,'wireBytes':2486,'slotLimit':2500,'scientificApproval':False}
    assert saved['verification']=='unchecked'
    assert prepare(store,invoke)==saved and invoke.call_count==1


@pytest.mark.parametrize('size,allowed',[(2609,True),(2610,False)])
def test_encoding_enforces_exact_reserved_byte_limit_without_truncation(size,allowed):
    value=padded_basis(size);before=deepcopy(value)
    assert len(wire_text(value).encode())==size-109
    assert valid_plan_basis(store_for().value,value,{'E1':'original'}) is allowed
    assert value==before


@pytest.mark.parametrize('change',['foreign','duplicate','missing','extra','overlimit','truncated'])
def test_invalid_response_is_stored_and_never_replanned(change):
    value=padded_basis()
    if change=='foreign':value['sourceRefs']=['E99']
    elif change=='duplicate':value['sourceRefs']=['E1','E1']
    elif change=='missing':value['protocol'].pop('measurement')
    elif change=='extra':value['sourceFacts']=[]
    elif change=='overlimit':value=padded_basis(2610)
    raw=response(value)
    if change=='truncated':raw['finishReason']='length'
    store=store_for();invoke=Mock(return_value=raw)
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    saved=deepcopy(store.value['state']['experimentPlanning'])
    assert saved['status']=='invalid_response' and saved['response']==raw
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1 and store.value['state']['experimentPlanning']==saved


@pytest.mark.parametrize('change',['wire','wire_digest','audit','raw_basis','response','encoding_type'])
def test_tampered_ready_plan_is_rejected_before_any_provider_call(change):
    store=store_for();invoke=Mock(return_value=response(padded_basis()));prepare(store,invoke)
    saved=store.value['state']['experimentPlanning']
    if change=='wire':saved['encodedBasis'][1][0]+='changed'
    elif change=='wire_digest':saved['encodedBasisDigest']='changed'
    elif change=='audit':saved['basisEncodingAudit']['scientificApproval']=True
    elif change=='raw_basis':saved['basis']['protocol']['state']+='changed'
    elif change=='response':saved['response']['content']+=' '
    else:saved['basisEncodingVersion']=True
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    invoke.assert_not_called()


def test_legacy_failed_plan_stays_failed_and_cannot_opt_into_new_semantics():
    store=store_for(0);invoke=Mock(return_value=response(padded_basis()))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning']);store.value['experimentPlanEncodingContractVersion']=1
    invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原输入'):prepare(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


def test_unknown_pending_cannot_switch_encoding_or_repair_its_metadata_to_resend():
    store=store_for();invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    assert store.value['state']['experimentPlanning']['status']=='pending'
    store.value['state']['experimentPlanning']['basisEncodingVersion']=True;invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    invoke.assert_not_called()


@pytest.mark.parametrize('replacement',[None,True,'1',0,6])
def test_wire_contract_is_server_owned_immutable_and_type_strict(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design an experiment',
            'experimentPlanEncodingContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['experimentPlanEncodingContractVersion']==5 and enabled(value)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'experimentPlanEncodingContractVersion':replacement})
    finally:facade.shutdown()


def test_new_draft_input_cannot_exceed_original_envelope_even_with_valid_plan():
    store=store_for();saved=prepare(store,Mock(return_value=response(padded_basis())))
    with pytest.raises(DeepResearchError,match='容量'):
        prepare_draft(store.value,saved,prompt='x'*24001,checkpoint=store.checkpoint)
    assert 'draftRequest' not in store.value['state']['experimentPlanning']


@pytest.mark.parametrize('version',[0,1])
def test_actual_generation_sends_explicit_legend_complete_evidence_and_exact_plan_values(version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_representation import wrapped_claims
    value=padded_basis();store=store_for(version)
    body={'sections':[],'claims':wrapped_claims()};raw=deepcopy(body)
    invoke=Mock(side_effect=[response(value),response(body)])
    if version==0:
        with pytest.raises(DeepResearchError):make_synthesize_node(invoke,store.update)({'run_id':'r'})
        assert invoke.call_count==1
    else:
        result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
        assert 'error_code' not in result and invoke.call_count==2 and body==raw
        planner,draft=invoke.call_args_list
        assert LEGEND in draft.args[2] and wire_text(value) in draft.args[2]
        assert 'Aim below2500UTF-8' in planner.args[2] and '2500-byte tuple' in planner.args[2]
        assert 'within4000' not in planner.args[2]
        assert all(len(c.args[2].encode())<=24000 for c in (planner,draft))
        assert all(store.value['state']['evidence'][0]['quote'] in c.args[2] for c in (planner,draft))
        assert store.value['state']['experimentPlanning']['basis']==value
        assert not any(c.get('verification') for c in store.value['state']['reportBody']['claims'])
