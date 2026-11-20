from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.experiment_blueprint import columns
from services.deep_research.experiment_planning import parsed_basis
from services.deep_research.planning_shape import response_value
from services.deep_research.structured_output import messages
from test_deep_research_compact_generation_rules import current as old_record
from test_deep_research_request_sized_blueprint import larger
from test_deep_research_blueprint_shared_wire import prepare
from test_deep_research_experiment_planning import Store, response


def record(version=15):
    r=old_record()
    r.update(structuredOutputContractVersion=version,experimentGenerationEnvelopeContractVersion=3)
    return r


def misplaced():
    value=columns(larger())
    value['pairingBudget']=value['protocol'].pop('pairingBudget')
    return value


def test_unique_move_preserves_every_value_raw_response_and_unverified_status():
    value=misplaced();raw=response(value);original=deepcopy(raw)
    normalized,audit=response_value(raw,json.loads,record())
    restored=deepcopy(normalized)
    restored['pairingBudget']=restored['protocol'].pop('pairingBudget')
    assert restored==value and raw==original
    assert audit['originalValueDigest']==digest(value)
    assert audit['normalizedValueDigest']==digest(columns(larger()))
    assert audit['moves']==[{'from':'/pairingBudget','to':'/protocol/pairingBudget'}]
    assert audit['rawResponseDigest']==digest(raw) and audit['scientificApproval'] is False
    assert parsed_basis(raw,json.loads,record())==larger()


@pytest.mark.parametrize('version',range(1,15))
def test_all_historical_versions_keep_original_response_interpretation(version):
    raw=response(misplaced())
    value,audit=response_value(raw,json.loads,record(version))
    assert value==misplaced() and audit is None
    assert parsed_basis(raw,json.loads,record(version)) is None


@pytest.mark.parametrize('change',['duplicate','extra_root','extra_protocol','missing_other','not_object'])
def test_conflicting_or_incomplete_shapes_are_never_guessed(change):
    value=misplaced()
    if change=='duplicate':value['protocol']['pairingBudget']=deepcopy(value['pairingBudget'])
    elif change=='extra_root':value['other']='keep me'
    elif change=='extra_protocol':value['protocol']['other']='keep me'
    elif change=='missing_other':value['protocol'].pop('data')
    else:value['pairingBudget']='unparsed budget'
    normalized,audit=response_value(response(value),json.loads,record())
    assert normalized==value and audit['moves']==[]
    assert parsed_basis(response(value),json.loads,record()) is None


def test_ready_resume_requires_matching_audit_and_never_resends():
    store=Store(record());raw=response(misplaced());invoke=Mock(return_value=raw)
    plan=prepare(store,invoke)
    assert plan['status']=='ready' and plan['verification']=='unchecked'
    assert plan['response']==raw and plan['responseShapeAudit']['moves']
    assert prepare(store,invoke)==plan and invoke.call_count==1
    store.value['state']['experimentPlanning']['responseShapeAudit']['moves']=[]
    with pytest.raises(DeepResearchError,match='结构记录'):prepare(store,invoke)
    assert invoke.call_count==1


def test_contract_change_cannot_reinterpret_a_frozen_pending_or_failed_plan():
    for fail in (True,False):
        store=Store(record(14));invoke=Mock(side_effect=RuntimeError('unknown') if fail else None,
            return_value=response(misplaced()))
        with pytest.raises((RuntimeError,DeepResearchError)):prepare(store,invoke)
        store.value['structuredOutputContractVersion']=15
        with pytest.raises(DeepResearchError,match='原输入不一致'):prepare(store,invoke)
        assert invoke.call_count==1


@pytest.mark.parametrize('change',['foreign_source','bad_row','bad_cap'])
def test_move_does_not_relax_source_state_or_budget_validation(change):
    value=misplaced()
    if change=='foreign_source':value['sourceRefs']=['unknown']
    elif change=='bad_row':value['protocol']['state']['blocks'][0]['states'][0].append('extra')
    else:value['pairingBudget']['phases'][0][4]=-1
    store=Store(record());invoke=Mock(return_value=response(value))
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    assert store.value['state']['experimentPlanning']['status']=='invalid_response'
    assert invoke.call_count==1


def test_correct_shapes_and_wire_messages_stay_identical_without_moves():
    value=columns(larger());normalized,audit=response_value(response(value),json.loads,record())
    assert normalized==value and not audit['moves']
    for node in ('plan_experiment','synthesize','verify_design_science'):
        assert messages(node,'Original source',15)==messages(node,'Original source',14)
