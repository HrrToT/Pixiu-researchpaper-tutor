from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_plan_encoding import decode,flexible,wire_text
from services.deep_research.experiment_planning import prepare_draft,valid_plan_basis
from test_deep_research_plan_encoding import store_for,prepare,padded_basis
from test_deep_research_experiment_planning import response


def test_full_plan_larger_than_preferred_slot_is_kept_unchecked_under_existing_raw_safety_limit():
    basis=padded_basis(2859);before=deepcopy(basis);store=store_for(2)
    invoke=Mock(return_value=response(basis));saved=prepare(store,invoke)
    assert saved['basis']==basis==before and decode(saved['encodedBasis'])==basis
    assert saved['basisEncodingVersion']==2 and saved['verification']=='unchecked'
    assert len(wire_text(basis).encode())==2750
    assert saved['basisEncodingAudit']=={'rawBytes':2859,'wireBytes':2750,'preferredSlotBytes':2500,
        'rawLimitBytes':4000,'fitsPreferredSlot':False,'scientificApproval':False}
    assert prepare(store,invoke)==saved and invoke.call_count==1


@pytest.mark.parametrize('size,accepted',[(2609,True),(2610,True),(4000,True),(4001,False)])
def test_existing_raw_limit_remains_a_hard_boundary(size,accepted):
    value=padded_basis(size);store=store_for(2);before=deepcopy(value)
    assert valid_plan_basis(store.value,value,{'E1':'original'}) is accepted
    assert value==before


def test_valid_but_oversized_response_has_sticky_capacity_status_without_another_call():
    store=store_for(2);value=padded_basis(4001);invoke=Mock(return_value=response(value))
    with pytest.raises(DeepResearchError) as exc:prepare(store,invoke)
    assert exc.value.code=='experiment_planning_output_capacity'
    frozen=deepcopy(store.value['state']['experimentPlanning']);checkpoints=len(store.checkpoints)
    assert frozen['status']=='output_capacity' and frozen['basis']==value and frozen['response']==response(value)
    with pytest.raises(DeepResearchError) as again:prepare(store,invoke)
    assert again.value.code=='experiment_planning_output_capacity' and invoke.call_count==1
    assert store.value['state']['experimentPlanning']==frozen and len(store.checkpoints)==checkpoints


@pytest.mark.parametrize('kind',['foreign','duplicate','missing','extra','nonstring','truncated'])
def test_malformed_or_unauthorized_plans_are_not_misclassified_as_capacity(kind):
    value=padded_basis(4001)
    if kind=='foreign':value['sourceRefs']=['foreign']
    elif kind=='duplicate':value['sourceRefs']=['E1','E1']
    elif kind=='missing':value['protocol'].pop('measurement')
    elif kind=='extra':value['newScientificField']='not allowed'
    elif kind=='nonstring':value['protocol']['state']=True
    raw=response(value)
    if kind=='truncated':raw['finishReason']='length'
    store=store_for(2);invoke=Mock(return_value=raw)
    with pytest.raises(DeepResearchError) as exc:prepare(store,invoke)
    assert exc.value.code=='invalid_experiment_planning_response'
    assert store.value['state']['experimentPlanning']['status']=='invalid_response'
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert invoke.call_count==1


@pytest.mark.parametrize('kind',['response','basis','audit','encoding_version'])
def test_tampered_capacity_response_cannot_be_reused_or_resent(kind):
    store=store_for(2);invoke=Mock(return_value=response(padded_basis(4001)))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    saved=store.value['state']['experimentPlanning']
    if kind=='response':saved['response']['content']+=' '
    elif kind=='basis':saved['basis']['protocol']['state']+='changed'
    elif kind=='audit':saved['basisEncodingAudit']['scientificApproval']=True
    else:saved['basisEncodingVersion']=True
    invoke.reset_mock()
    with pytest.raises(DeepResearchError) as exc:prepare(store,invoke)
    assert exc.value.code=='invalid_experiment_planning_state';invoke.assert_not_called()


def test_complete_generation_request_is_still_limited_by_actual_utf8_bytes():
    store=store_for(2);saved=prepare(store,Mock(return_value=response(padded_basis(2859))))
    request=prepare_draft(store.value,saved,prompt='汉'*8000,checkpoint=store.checkpoint)
    assert len(request['prompt'].encode())==24000
    late=deepcopy(store.value);late['budget']['elapsedSeconds']=350
    assert prepare_draft(late,store.value['state']['experimentPlanning'],prompt='汉'*8000,checkpoint=store.checkpoint)==request


def test_oversized_generation_is_saved_as_known_pre_send_refusal_and_cannot_change_or_resend():
    store=store_for(2);saved=prepare(store,Mock(return_value=response(padded_basis(2859))))
    with pytest.raises(DeepResearchError) as exc:
        prepare_draft(store.value,saved,prompt='汉'*8001,checkpoint=store.checkpoint)
    assert exc.value.code=='experiment_drafting_input_capacity'
    frozen=deepcopy(store.value['state']['experimentPlanning']);count=len(store.checkpoints)
    assert frozen['draftStatus']=='not_started_capacity' and 'draftRequest' not in frozen
    assert frozen['basis']==saved['basis'] and frozen['draftCapacity']['inputBytes']==24003
    with pytest.raises(DeepResearchError) as again:
        prepare_draft(store.value,frozen,prompt='汉'*8001,checkpoint=store.checkpoint)
    assert again.value.code=='experiment_drafting_input_capacity' and len(store.checkpoints)==count
    with pytest.raises(DeepResearchError) as changed:
        prepare_draft(store.value,frozen,prompt='now shorter',checkpoint=store.checkpoint)
    assert changed.value.code=='invalid_experiment_planning_state'
    assert store.value['state']['experimentPlanning']==frozen


@pytest.mark.parametrize('state',['failed','unknown'])
def test_legacy_failed_and_unknown_plans_never_opt_into_flexible_capacity(state):
    store=store_for(1);invoke=Mock(return_value=response(padded_basis(2859)))
    if state=='unknown':invoke.side_effect=OSError('unknown')
    with pytest.raises((DeepResearchError,OSError)):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning']);store.value['experimentPlanEncodingContractVersion']=2
    invoke.reset_mock()
    with pytest.raises(DeepResearchError) as exc:prepare(store,invoke)
    assert exc.value.code=='invalid_experiment_planning_state'
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


@pytest.mark.parametrize('version',[None,False,True,0,'2',1,3])
def test_flexible_capacity_is_strictly_version_two(version):
    assert flexible(store_for(version).value) is False
