from copy import deepcopy
import json
from unittest.mock import Mock, patch

import pytest

from services.deep_research.experiment_protocol import (
    protocol_errors,stamp_protocol_contract,enforce_protocol_consistency,claim_protocol_text)
from services.deep_research.execution_materialization import materialize_execution_claim,verification_claim_view
from services.deep_research.verification import verify_claims
from services.deep_research.design_audit import validate_design_audit
from services.deep_research.graph import make_synthesize_node,make_publish_node
from services.deep_research.repair import repair_rejected
from services.deep_research.tools import BudgetedSemanticChecker


def operation(action,**parameters):
    return {'action':action,'parameters':[{'name':name,'type':'number' if type(value) in (int,float) else 'choice','value':value}
                                       for name,value in parameters.items()]}


def controls():
    return {'initialization':operation('Initialize one enhancement state using the proposed seeded procedure, then copy baseline and enhancement state to both arms.',seed=0,initial_opacity=0.1),
            'rendering':operation('Resize both observed/reference and rendered images to this size, scaling camera intrinsics consistently.',renderer='Differentiable Gaussian rasterization',width=512,height=512),
            'optimizer':operation('Use constant rates for the declared trainable groups.',optimizer='Adam',opacity_lr=0.001,enhancement_lr=0.001),
            'otherInterventions':operation('Disable quantization, occupancy removal and compaction in both arms.')}


def data():
    return {'dataset':'Cited dataset','scenes':{'mode':'named','names':['Example']},
            'split':{'mode':'seeded_fraction','evaluationFraction':0.2,'seed':0},
            'seeds':[0],'independentUnit':'one scene, descriptive paired view differences',
            'replication':{'mode':'fixed_checkpoint'}}


def claim(role='controls',spec=None):
    return {'claimId':role,'kind':'proposal','designRole':role,'designContractVersion':2,
            'protocolContractVersion':1,'text':'Proposed unexecuted settings; original prose remains visible.',
            'evidenceRefs':[],'executionSpec':deepcopy(spec if spec is not None else controls())}


def passed(claims,evidence):
    return [{'claimId':c['claimId'],'status':'passed'} for c in claims]


def test_valid_controls_are_explicit_and_never_claim_experiment_execution():
    c=claim();before=deepcopy(c)
    assert protocol_errors('controls',c['executionSpec'])==[]
    rendered=materialize_execution_claim(c)
    assert rendered['text'].startswith(c['text']) and '512' in rendered['text'] and '0.001' in rendered['text']
    assert '尚未执行' in rendered['text']
    assert materialize_execution_claim(rendered)==rendered
    assert verification_claim_view(rendered)==c and c==before
    assert not verify_claims([rendered],[])['accepted']
    assert verify_claims([rendered],[],passed)['accepted'][0]['verification']=='proposal'


@pytest.mark.parametrize('slot',['initialization','rendering','optimizer','otherInterventions'])
def test_missing_operation_cannot_be_approved_by_semantic_stub(slot):
    c=claim();del c['executionSpec'][slot]
    checker=Mock(side_effect=passed)
    result=verify_claims([c],[],checker)
    assert not result['accepted'] and result['rejected'][0]['reason']=='incomplete_experiment_protocol'
    checker.assert_not_called()


@pytest.mark.parametrize('slot',['initialization','rendering','optimizer'])
def test_same_setting_without_parameters_is_rejected(slot):
    c=claim();c['executionSpec'][slot]=operation('Use the same settings.')
    assert protocol_errors('controls',c['executionSpec'])


@pytest.mark.parametrize('value',[True,False,float('nan'),float('inf'),'unknown'])
def test_numeric_parameter_cannot_be_a_boolean_nonfinite_or_placeholder(value):
    c=claim();c['executionSpec']['optimizer']['parameters'][1]['value']=value
    assert protocol_errors('controls',c['executionSpec'])


def test_duplicate_parameter_and_unrecognized_wrapper_remain_invalid():
    c=claim();c['executionSpec']['rendering']['parameters']*=2
    assert protocol_errors('controls',c['executionSpec'])
    assert protocol_errors('controls',{'controls':controls()})


def test_typed_audit_binds_only_exact_operation_and_value():
    c=claim()
    fields={'paired_initialization':'initialization','render_settings':'rendering',
            'optimizer_settings':'optimizer','other_interventions':'otherInterventions'}
    audit={'designAudit':{slot:{'fields':[{'claimId':'controls','path':['executionSpec',field],
                                          'value':c['executionSpec'][field]}]} for slot,field in fields.items()}}
    assert validate_design_audit(c,audit,[])==[]
    wrong=deepcopy(audit);wrong['designAudit']['render_settings']['fields'][0]['value']['parameters'][1]['value']=999
    assert validate_design_audit(c,wrong,[])==['render_settings']
    legacy=deepcopy(c);legacy.pop('protocolContractVersion')
    assert set(validate_design_audit(legacy,audit,[]))==set(fields)


def test_budgeted_reviewer_can_bind_controls_without_retranscribing_settings():
    c=materialize_execution_claim(claim())
    fields={'paired_initialization':'initialization','render_settings':'rendering',
            'optimizer_settings':'optimizer','other_interventions':'otherInterventions'}
    def invoke(**kwargs):
        assert 'Protocol contract 1' in kwargs['prompt']
        assert '512' in kwargs['prompt'] and '0.001' in kwargs['prompt']
        verdict={'claimId':'controls','status':'passed','designAudit':{
            slot:{'fields':[{'claimId':'controls','path':['executionSpec',key],
                            'value':c['executionSpec'][key]}]} for slot,key in fields.items()}}
        return {'content':json.dumps([verdict])}
    result=verify_claims([c],[],BudgetedSemanticChecker(invoke,'r'))
    assert result['accepted'][0]['protocolContractVersion']==1
    assert result['accepted'][0]['executionSpec']==controls()


def test_precheck_does_not_establish_dataset_availability_without_source_support():
    c=materialize_execution_claim(claim('data',data()))
    slots={'scenes':'scenes','split':'split','seeds':'seeds','sampling_unit':'independentUnit'}
    def invoke(**kwargs):
        verdict={'claimId':'data','status':'passed','designAudit':{
            slot:{'fields':[{'claimId':'data','path':['executionSpec',key],
                            'value':c['executionSpec'][key]}]} for slot,key in slots.items()}}
        return {'content':json.dumps([verdict])}
    result=verify_claims([c],[],BudgetedSemanticChecker(invoke,'r'))
    assert not result['accepted'] and 'DA_MISSING' in result['rejected'][0]['detail']


def test_data_protocol_states_prechecks_instead_of_claiming_original_counts():
    c=claim('data',data());rendered=materialize_execution_claim(c)
    assert protocol_errors('data',c['executionSpec'])==[]
    assert '执行前预检' in rendered['text'] and '否则停止实验' in rendered['text']
    assert '不表示论文已报告或系统已确认样本数量' in rendered['text']
    assert 'min(N−1,max(1,floor(N×评估比例)))' in rendered['text']
    assert verification_claim_view(rendered)==c
    wrong=deepcopy(c);wrong['executionSpec']['split']['selectionProcedure']='Use unknown official defaults.'
    assert protocol_errors('data',wrong['executionSpec'])==['split.unrecognized_fields']


def test_legacy_claim_is_not_implicitly_reinterpreted_as_new_contract():
    c=claim();c.pop('protocolContractVersion');c.pop('executionSpec')
    original=deepcopy(c)
    assert materialize_execution_claim(c)==c
    assert verify_claims([c],[],passed)['accepted']
    assert enforce_protocol_consistency({'accepted':[c],'rejected':[]})['accepted']==[c]
    assert not enforce_protocol_consistency({'accepted':[c],'rejected':[]},required=True)['accepted']
    assert c==original


@pytest.mark.parametrize('enabled',[False,True])
def test_run_snapshot_controls_opt_in_model_cannot_choose_protocol_version(enabled):
    c=claim();c['protocolContractVersion']=999
    record={'question':'Propose a controlled experiment.','state':{'outputKind':'experiment_design','evidence':[],'plan':[]}}
    if enabled:record['protocolContractVersion']=1
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return record
    def invoke(run,node,prompt,options,**kwargs):
        assert ('Protocol contract 1' in prompt)==enabled
        return {'content':json.dumps({'protocolContractVersion':999,'claims':[c]})}
    make_synthesize_node(invoke,update)({'run_id':'r'})
    result=record['state']['reportBody']
    if enabled:
        assert result['protocolContractVersion']==result['claims'][0]['protocolContractVersion']==1
        assert '512' in result['claims'][0]['text']
    else:
        assert 'protocolContractVersion' not in result and 'protocolContractVersion' not in result['claims'][0]


def test_repair_cannot_remove_server_protocol_version_or_hide_its_config():
    c=claim()
    revised={**c,'protocolContractVersion':999,'text':'Revised prospective controls.'}
    result=repair_rejected({'claims':[c]},{'rejected':[{'claimId':'controls','reason':'incomplete'}]},[],
        'Specify controls.',lambda _: {'content':json.dumps([revised])},json.loads)
    assert result[0]['protocolContractVersion']==1 and '512' in result[0]['text']


def test_publish_revalidates_marked_protocol_and_invalidates_stale_completion():
    c=claim();del c['executionSpec']['rendering'];c['verification']='proposal'
    record={'protocolContractVersion':1,'state':{'outputKind':'experiment_design','verifiedReport':{
        'verifiedClaims':[c],'rejectedClaims':[],'answerCoverage':{'status':'checked','gaps':[]}}}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return record
    publish=Mock(return_value=({'publicationId':'p'},True))
    result=make_publish_node(publish,update)({'run_id':'r'})
    assert result['outcome']=='inconclusive' and not publish.call_args.kwargs['payload']['claims']
    assert record['state']['verifiedReport']['answerCoverage']['status']=='invalidated_design_contract'
