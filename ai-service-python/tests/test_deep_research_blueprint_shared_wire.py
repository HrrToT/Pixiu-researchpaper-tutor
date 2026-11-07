from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.blueprint_wire import pack,unpack,PLANNING,LEGEND
from services.deep_research.experiment_blueprint import columns
from services.deep_research.experiment_plan_encoding import encode,decode,wire_text
from services.deep_research.experiment_planning import prepare_plan,valid_plan_basis,basis_encoding_audit
from services.deep_research.structured_output import messages,ARRAY_NODES,PRIVATE_SHARED_POLICY
from services.deep_research.contracts import DeepResearchError
from services.deep_research.graph import make_synthesize_node
from test_deep_research_trainable_state_lists import basis,record as list_record
from test_deep_research_experiment_planning import Store,response
from test_deep_research_experiment_representation import wrapped_claims


def record():
    r=list_record();r.update(experimentPlanEncodingContractVersion=6,structuredOutputContractVersion=12)
    return r


def prepare(s,invoke):
    return prepare_plan(s.value,prompt=PLANNING+'Original source evidence',aliases={'E1':'original'},
        invoke=invoke,parse=json.loads,checkpoint=s.checkpoint)


def test_exact_dtype_and_unique_state_names_are_shared_without_source_or_choice_inference():
    b=basis();states=b['protocol']['state']['blocks'][0]['states']
    b['protocol']['pairingBudget']['phases'][0]['trainables']=[states[0]['name'],'uncreated state']
    original=deepcopy(b);wire=pack(b)
    assert wire[1][2][1]=='float32' and len(wire[1][2][2][0][1][0])==3
    assert wire[1][5][0][0][5]==[0,'uncreated state']
    assert unpack(wire)==b and decode(encode(b,version=6),version=6)==b and b==original
    wire[1][5][0][0][4]=999
    assert b==original
    assert not b.get('scientificApproval')


def test_mixed_dtypes_are_preserved_with_no_global_default():
    b=basis();b['protocol']['state']['blocks'][0]['states'][0]['dtype']='float64'
    wire=pack(b)
    assert wire[1][2][1] is None and len(wire[1][2][2][0][1][0])==4
    assert unpack(wire)==b


def test_ambiguous_names_stay_literal_and_never_select_a_block_by_guess():
    b=basis();other=deepcopy(b['protocol']['state']['blocks'][0]);other['name']='other'
    b['protocol']['state']['blocks'].append(other)
    b['protocol']['pairingBudget']['phases'][0]['trainables']=['layer0.weight']
    wire=pack(b)
    assert wire[1][5][0][0][5]==['layer0.weight'] and unpack(wire)==b
    wire[1][5][0][0][5]=[0]
    with pytest.raises(ValueError,match='ambiguous'):decode(wire,version=6)


@pytest.mark.parametrize('bad',[True,-1,999,{},[],None,0.5])
def test_state_indices_are_exact_in_range_integers_and_never_python_negative_or_bool_indices(bad):
    b=basis();b['protocol']['pairingBudget']['phases'][0]['trainables']=['layer0.weight']
    wire=pack(b);wire[1][5][0][0][5]=[bad]
    with pytest.raises(ValueError):decode(wire,version=6)


def repeated():
    b=basis();states=b['protocol']['state']['blocks'][0]['states']
    for i in range(12):states.append({**deepcopy(states[0]),'name':f'large_explicit_state_{i}'})
    names=[s['name'] for s in states]
    for phase in b['protocol']['pairingBudget']['phases']:phase['trainables']=names[:]
    b['protocol']['measurement']+='x'*1100
    return b


def test_bigger_raw_object_can_fit_original_wire_cap_with_all_explicit_states_and_caps_retained():
    b=repeated();old_bytes=len(wire_text(b,version=5).encode());new_bytes=len(wire_text(b,version=6).encode())
    assert old_bytes>4000 and new_bytes<4000
    assert not valid_plan_basis(list_record(),b,{'E1':'original'})
    assert valid_plan_basis(record(),b,{'E1':'original'})
    s=Store(record());invoke=Mock(return_value=response(columns(b)));saved=prepare(s,invoke)
    assert saved['response']==response(columns(b)) and saved['basis']==b
    assert decode(saved['encodedBasis'],version=6)==b
    assert saved['basisEncodingAudit']['rawLimitBytes']==8192
    assert saved['basisEncodingAudit']['wireLimitBytes']==4000
    assert not saved['basisEncodingAudit']['scientificApproval']
    assert saved['verification']=='unchecked' and invoke.call_count==1


@pytest.mark.parametrize('change',['wire_overflow','raw_overflow','foreign_ref','missing_states'])
def test_actual_wire_source_and_raw_storage_guards_still_refuse_without_truncation(change):
    b=repeated()
    if change=='wire_overflow':b['protocol']['measurement']+='unique-value-'*400
    elif change=='raw_overflow':
        # Repeated references can be tiny on wire, but original response storage is independently bounded.
        b=basis()
        name='x'*600;b['protocol']['state']['blocks'][0]['states'][0]['name']=name
        for p in b['protocol']['pairingBudget']['phases']:p['trainables']=[name]
        for i in range(12):
            p=deepcopy(b['protocol']['pairingBudget']['phases'][0]);p['name']=f'p{i}'
            b['protocol']['pairingBudget']['phases'].append(p)
        assert len(wire_text(b,version=6).encode())<4000
        assert len(json.dumps(columns(b),separators=(',',':')).encode())>8192
    elif change=='foreign_ref':b['sourceRefs']=['P1']
    else:b['protocol']['state']['blocks']=[]
    assert not valid_plan_basis(record(),b,{'E1':'original'})
    assert decode(encode(repeated(),version=6),version=6)==repeated()


def test_pending_unshared_blueprint_cannot_change_encoding_and_resend():
    s=Store(list_record());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(s,invoke)
    saved=deepcopy(s.value['state']['experimentPlanning']);s.value.update(
        experimentPlanEncodingContractVersion=6,structuredOutputContractVersion=12)
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(s,invoke)
    invoke.assert_not_called();assert s.value['state']['experimentPlanning']==saved


def test_actual_graph_uses_shared_complete_plan_and_original_source_quotes_without_a_second_model_call():
    s=Store(record());b=repeated();invoke=Mock(side_effect=[response(columns(b)),
        response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,s.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    first,second=invoke.call_args_list
    assert PLANNING in first.args[2] and LEGEND in second.args[2]
    assert wire_text(b,version=6) in second.args[2]
    assert all(s.value['state']['evidence'][0]['quote'] in c.args[2] for c in (first,second))
    saved=s.value['state']['experimentPlanning']
    assert saved['basis']==b and saved['basisEncodingAudit']==basis_encoding_audit(s.value,b)
    assert not any(c.get('verification') for c in s.value['state']['reportBody']['claims'])


def test_system_and_planner_agree_on_separate_raw_and_actual_wire_caps_and_public_messages_stay_exact():
    assert 'raw JSON <=8192' in PLANNING and 'hard raw cap8192' in PLANNING
    assert 'raw JSON<=8192' in PRIVATE_SHARED_POLICY
    assert len(PRIVATE_SHARED_POLICY.encode())+128<=1024
    for n in ARRAY_NODES|{'synthesize','synthesize_audience','resolve_brief'}:
        assert messages(n,'原文',12,prospective=True)==messages(n,'原文',9,prospective=True)
