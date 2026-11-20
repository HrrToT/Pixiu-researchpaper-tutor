from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_blueprint import valid_budget,columns,PLANNING_STATE_LISTS,LEGEND_STATE_LISTS
from services.deep_research.experiment_plan_encoding import encode,decode,wire_text
from services.deep_research.experiment_planning import prepare_plan,valid_plan_basis
from services.deep_research.structured_output import messages,ARRAY_NODES,PRIVATE_STATE_LIST_POLICY
from services.deep_research.graph import make_synthesize_node
from test_deep_research_execution_blueprint import basis as object_basis
from test_deep_research_blueprint_columns import record as column_record
from test_deep_research_experiment_planning import Store,response
from test_deep_research_experiment_representation import wrapped_claims


def record():
    r=column_record();r.update(experimentPlanEncodingContractVersion=5,structuredOutputContractVersion=11)
    return r


def basis():
    b=object_basis()
    for p in b['protocol']['pairingBudget']['phases']:p['trainables']=[p['trainables']]
    b['protocol']['pairingBudget']['phases'][0]['unit']='steps'
    return b


def prepare(s,invoke):
    return prepare_plan(s.value,prompt=PLANNING_STATE_LISTS+'Original evidence',aliases={'E1':'original'},
        invoke=invoke,parse=json.loads,checkpoint=s.checkpoint)


def test_trainable_names_and_step_label_roundtrip_literally_without_parameter_or_cap_changes():
    b=basis();original=deepcopy(b)
    assert valid_budget(b['protocol']['pairingBudget'],state_lists=True)
    assert not valid_budget(b['protocol']['pairingBudget'])
    assert valid_plan_basis(record(),b,{'E1':'original'})
    assert not valid_plan_basis(column_record(),b,{'E1':'original'})
    raw=columns(b);wire=encode(b,version=5)
    assert decode(wire,version=5)==b and columns(raw,expand=True)==b and b==original
    assert raw['protocol']['pairingBudget']['phases'][0][3]=='steps'
    assert raw['protocol']['pairingBudget']['phases'][0][5]==['reference states']
    with pytest.raises(ValueError):decode(wire,version=4)


@pytest.mark.parametrize('change',['string','duplicate','blank','nonstring','nested','too_many','positive_empty',
    'negative_cap','bool_cap','fractional_steps','infinite','unknown_unit','frame_unit'])
def test_names_are_typed_and_unique_and_fitting_units_and_caps_remain_bounded(change):
    b=basis()['protocol']['pairingBudget'];p=b['phases'][0]
    if change=='string':p['trainables']='opaque field'
    elif change=='duplicate':p['trainables']=['state','state']
    elif change=='blank':p['trainables']=[' ']
    elif change=='nonstring':p['trainables']=[True]
    elif change=='nested':p['trainables']=[['state']]
    elif change=='too_many':p['trainables']=[str(i) for i in range(129)]
    elif change=='positive_empty':p['trainables']=[]
    elif change=='negative_cap':p['cap']=-1
    elif change=='bool_cap':p['cap']=True
    elif change=='fractional_steps':p['cap']=0.5
    elif change=='infinite':p['cap']=float('inf')
    elif change=='unknown_unit':p['unit']='iterations_or_epochs'
    else:p['unit']='video_frames'
    assert not valid_budget(b,state_lists=True)


def test_explicit_skipped_phase_can_have_no_trainable_state_without_creating_any_default():
    b=basis();p=b['protocol']['pairingBudget']['phases'][0];p.update(cap=0,trainables=[])
    original=deepcopy(b);s=Store(record());invoke=Mock(return_value=response(columns(b)))
    saved=prepare(s,invoke)
    assert saved['basis']==original and saved['verification']=='unchecked'
    assert saved['basisEncodingAudit']['scientificApproval'] is False
    assert decode(saved['encodedBasis'],version=5)==original
    assert prepare(s,invoke)==saved and invoke.call_count==1


def test_public_budget1_still_rejects_private_step_alias_and_has_no_new_state_list_fields():
    from services.deep_research.budget_spec import validate_budget_spec
    from test_deep_research_shared_experiment_repair import inputs
    b=deepcopy(next(c['executionSpec'] for c in inputs()[0]['claims'] if c['designRole']=='budget'))
    assert not validate_budget_spec(b)
    b['baseline']['unit']='steps'
    assert validate_budget_spec(b)
    assert set(b)=={'baseline','recovery'}


@pytest.mark.parametrize('change',['foreign_ref','duplicate_ref','missing_module','bad_type','capacity'])
def test_citation_state_and_original4kb_checks_are_not_replaced_by_accepting_lists(change):
    b=basis()
    if change=='foreign_ref':b['sourceRefs']=['P1']
    elif change=='duplicate_ref':b['sourceRefs']*=2
    elif change=='missing_module':b['protocol']['state']['blocks']=[]
    elif change=='bad_type':b['protocol']['measurement']={'quality':'not a string'}
    else:b['protocol']['measurement']='x'*4001
    assert not valid_plan_basis(record(),b,{'E1':'original'})


def test_pending_column_plan_cannot_upgrade_lists_or_private_transport_and_resend():
    s=Store(column_record());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(s,invoke)
    saved=deepcopy(s.value['state']['experimentPlanning']);s.value.update(
        experimentPlanEncodingContractVersion=5,structuredOutputContractVersion=11)
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(s,invoke)
    invoke.assert_not_called();assert saved==s.value['state']['experimentPlanning']


def test_actual_graph_sends_exact_named_state_choices_but_grants_no_scientific_approval():
    s=Store(record());b=basis();invoke=Mock(side_effect=[response(columns(b)),
        response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,s.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    first,second=invoke.call_args_list
    assert PLANNING_STATE_LISTS in first.args[2]
    assert LEGEND_STATE_LISTS in second.args[2] and wire_text(b,version=5) in second.args[2]
    saved=s.value['state']['experimentPlanning']
    assert saved['basis']==b and saved['basisEncodingVersion']==5
    assert saved['request']['messages'][0]['content']==PRIVATE_STATE_LIST_POLICY
    assert not any(c.get('verification') for c in s.value['state']['reportBody']['claims'])


def test_private_state_list_schema_and_transport_agree_without_changing_public_messages():
    schema=json.JSONDecoder().raw_decode(PLANNING_STATE_LISTS[PLANNING_STATE_LISTS.index('{'):])[0]
    assert isinstance(schema['protocol']['pairingBudget']['phases'][0][5],list)
    assert len(PRIVATE_STATE_LIST_POLICY.encode())+128<=1024
    assert 'trainables is a unique state-name list' in PRIVATE_STATE_LIST_POLICY
    for node in ARRAY_NODES|{'synthesize','synthesize_audience','resolve_brief'}:
        assert messages(node,'原文',11,prospective=True)==messages(node,'原文',9,prospective=True)
