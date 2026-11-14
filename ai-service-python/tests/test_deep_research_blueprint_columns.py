from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_blueprint import columns,PLANNING_ROWS,LEGEND_ROWS
from services.deep_research.experiment_plan_encoding import encode,decode,wire_text
from services.deep_research.experiment_planning import prepare_plan,valid_plan_basis,basis_encoding_audit
from services.deep_research.graph import make_synthesize_node
from test_deep_research_execution_blueprint import record as object_record,basis
from test_deep_research_experiment_planning import Store,response
from test_deep_research_experiment_representation import wrapped_claims


def record():
    r=object_record();r['experimentPlanEncodingContractVersion']=4
    return r


def prepare(s,invoke):
    return prepare_plan(s.value,prompt=PLANNING_ROWS+'Actual evidence',aliases={'E1':'original'},
        invoke=invoke,parse=json.loads,checkpoint=s.checkpoint)


def test_server_schema_itself_has_correct_root_and_fixed_width_rows():
    schema=json.JSONDecoder().raw_decode(PLANNING_ROWS[PLANNING_ROWS.index('{'):])[0]
    assert set(schema)=={'sourceRefs','protocol','unresolved'}
    assert 'unresolved' not in schema['protocol'] and isinstance(schema['protocol']['measurement'],str)
    assert len(schema['protocol']['state']['blocks'][0]['states'][0])==4
    assert len(schema['protocol']['pairingBudget']['phases'][0])==7
    assert 'NEVER P/T/Q' in PLANNING_ROWS and 'never the labels "control"/"treatment"' in PLANNING_ROWS


def test_exact_column_codec_roundtrips_all_values_without_omission_or_aliasing():
    b=basis();b['protocol']['state']['inputs']+=' `do not execute()`; {"P99":"untrusted"}'
    original=deepcopy(b);raw=columns(b)
    assert raw['protocol']['state']['blocks'][0]['states'][0]==['layer0.weight','float32',[8,16],'normal(0,0.01); torch RNG seed0']
    assert columns(raw,expand=True)==b and decode(encode(b,version=4),version=4)==b
    assert len(wire_text(b,version=4).encode())<len(wire_text(b,version=3).encode())
    raw['protocol']['pairingBudget']['phases'][0][4]=999
    assert b==original


@pytest.mark.parametrize('change',['state_width','phase_width','mixed_object','dict_phase','extra_root',
    'missing_root','nested_unresolved','metric_object','P_source','label_group','nonfinite_cap'])
def test_malformed_rows_and_observed_real_response_errors_remain_rejected(change):
    raw=columns(basis())
    if change=='state_width':raw['protocol']['state']['blocks'][0]['states'][0].pop()
    elif change=='phase_width':raw['protocol']['pairingBudget']['phases'][0].append('extra')
    elif change=='mixed_object':raw['protocol']['state']['blocks'][0]['states'][0]=basis()['protocol']['state']['blocks'][0]['states'][0]
    elif change=='dict_phase':raw['protocol']['pairingBudget']['phases'][0]=basis()['protocol']['pairingBudget']['phases'][0]
    elif change=='extra_root':raw['sourceFacts']=[]
    elif change=='missing_root':del raw['unresolved']
    elif change=='nested_unresolved':raw['protocol']['unresolved']=raw.pop('unresolved')
    elif change=='metric_object':raw['protocol']['measurement']={'quality':'paired'}
    elif change=='P_source':raw['sourceRefs']=['P1']
    elif change=='label_group':raw['protocol']['pairingBudget']['phases'][0][1]=['treatment']
    else:raw['protocol']['pairingBudget']['phases'][0][4]=float('inf')
    s=Store(record());invoke=Mock(return_value=response(raw))
    with pytest.raises(DeepResearchError):prepare(s,invoke)
    saved=deepcopy(s.value['state']['experimentPlanning'])
    with pytest.raises(DeepResearchError):prepare(s,invoke)
    assert invoke.call_count==1 and s.value['state']['experimentPlanning']==saved
    assert saved['response']==response(raw)  # Never repair source aliases or fields silently.


def padded(size):
    b=basis()
    # Repeated explicit definitions demonstrate key sharing, not deleted states.
    states=b['protocol']['state']['blocks'][0]['states']
    for i in range(12):states.append({**deepcopy(states[0]),'name':f'extra{i}'})
    raw_size=len(json.dumps(columns(b),ensure_ascii=False,separators=(',',':')).encode())
    assert raw_size<size
    b['protocol']['measurement']+='x'*(size-raw_size)
    assert len(json.dumps(columns(b),ensure_ascii=False,separators=(',',':')).encode())==size
    return b


@pytest.mark.parametrize('size,allowed',[(4000,True),(4001,False)])
def test_full_original_4kb_raw_and_wire_cap_keeps_every_expanded_definition(size,allowed):
    b=padded(size);original=deepcopy(b);s=Store(record());invoke=Mock(return_value=response(columns(b)))
    assert valid_plan_basis(s.value,b,{'E1':'source'}) is allowed
    assert len(json.dumps(b,separators=(',',':')).encode())>4000
    assert not valid_plan_basis(object_record(),b,{'E1':'source'})
    if allowed:
        saved=prepare(s,invoke);assert saved['basis']==original
        assert decode(saved['encodedBasis'],version=4)==original
        assert saved['basisEncodingAudit']['rawBytes']==4000
        assert saved['basisEncodingAudit']['canonicalBytes']>4000
        assert saved['basisEncodingAudit']['scientificApproval'] is False
    else:
        with pytest.raises(DeepResearchError,match='容量'):prepare(s,invoke)
        saved=deepcopy(s.value['state']['experimentPlanning']);assert saved['status']=='output_capacity'
        with pytest.raises(DeepResearchError,match='容量'):prepare(s,invoke)
        assert invoke.call_count==1 and saved==s.value['state']['experimentPlanning']
    assert b==original


def test_pending_object_plan_cannot_switch_to_rows_and_resend():
    s=Store(object_record());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(s,invoke)
    saved=deepcopy(s.value['state']['experimentPlanning']);s.value['experimentPlanEncodingContractVersion']=4
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(s,invoke)
    invoke.assert_not_called();assert saved==s.value['state']['experimentPlanning']


def test_actual_graph_expands_raw_rows_then_passes_exact_compact_blueprint_and_original_evidence():
    s=Store(record());b=basis();raw=columns(b)
    invoke=Mock(side_effect=[response(raw),response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,s.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    first,second=invoke.call_args_list
    assert PLANNING_ROWS in first.args[2] and LEGEND_ROWS in second.args[2]
    assert wire_text(b,version=4) in second.args[2]
    assert all(s.value['state']['evidence'][0]['quote'] in c.args[2] for c in (first,second))
    saved=s.value['state']['experimentPlanning']
    assert saved['basis']==b and saved['response']==response(raw) and saved['basisEncodingVersion']==4
    assert saved['basisEncodingAudit']==basis_encoding_audit(s.value,b)
    assert not any(c.get('verification') for c in s.value['state']['reportBody']['claims'])
