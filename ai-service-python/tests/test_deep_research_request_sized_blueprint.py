from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_planning import valid_plan_basis, prepare_draft, basis_encoding_audit
from services.deep_research.experiment_plan_encoding import encode, decode, wire_text
from services.deep_research.graph import make_synthesize_node
from services.deep_research.experiment_blueprint import columns
from test_deep_research_blueprint_shared_wire import record, repeated, prepare
from test_deep_research_experiment_planning import Store, response


def larger():
    b = repeated()
    while len(wire_text(b, version=6).encode()) <= 4200:
        b['protocol']['measurement'] += ' bounded observation'
    return b


def current():
    r = record()
    r['experimentPlanEncodingContractVersion'] = 7
    return r


def test_complete_plan_can_exceed_old_internal_slot_without_truncation_or_approval():
    b = larger()
    assert not valid_plan_basis(record(), b, {'E1': 'original'})
    assert valid_plan_basis(current(), b, {'E1': 'original'})
    assert decode(encode(b, version=7), version=7) == b
    s = Store(current())
    invoke = Mock(side_effect=[response(columns(b)), response({'sections': [], 'claims': []})])
    make_synthesize_node(invoke, s.update)({'run_id': 'r'})
    assert invoke.call_count == 2
    body = invoke.call_args_list[1].args[2]
    assert wire_text(b, version=7) in body and len(body.encode()) <= 32000
    assert s.value['state']['evidence'][0]['quote'] in body
    assert not basis_encoding_audit(current(), b)['scientificApproval']


@pytest.mark.parametrize('change', ['raw_overflow', 'foreign_source', 'missing_states'])
def test_larger_slot_does_not_allow_unbounded_or_invalid_plans(change):
    b = larger()
    if change == 'raw_overflow': b['protocol']['measurement'] += 'x' * 8192
    elif change == 'foreign_source': b['sourceRefs'] = ['unknown']
    else: b['protocol']['state']['blocks'] = []
    assert not valid_plan_basis(current(), b, {'E1': 'original'})


def test_full_request_overflow_still_prevents_body_dispatch():
    r = current()
    from test_deep_research_experiment_capacity import sized_body, current as capacity_record
    r.update({key: value for key, value in capacity_record().items() if key.endswith("ContractVersion") or key == "outputKind"})
    r["experimentPlanEncodingContractVersion"] = 7
    s = Store(r)
    plan = {'experimentInputVersion': 1}
    body, audit = sized_body(r, 32001)
    with pytest.raises(DeepResearchError, match='容量'):
        prepare_draft(r, plan, prompt=body, checkpoint=s.checkpoint, outline_encoding_audit=audit)
    assert s.checkpoints[-1]['draftStatus'] == 'not_started_capacity'
    assert s.checkpoints[-1]['draftCapacity']['maxInputBytes'] == 32000


def test_old_pending_request_cannot_be_reinterpreted_under_new_capacity():
    s = Store(record())
    invoke = Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError): prepare(s, invoke)
    frozen = deepcopy(s.value['state']['experimentPlanning'])
    s.value['experimentPlanEncodingContractVersion'] = 7
    invoke.reset_mock()
    with pytest.raises(DeepResearchError): prepare(s, invoke)
    invoke.assert_not_called()
    assert s.value['state']['experimentPlanning'] == frozen
