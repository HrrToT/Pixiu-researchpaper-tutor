"""Prefer the existing prose editor without rewriting frozen scope or trusting edits."""
from copy import deepcopy
import json
from unittest.mock import Mock,patch

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.scope_compaction import compact
from services.deep_research.scope_expression import materialize
from test_deep_research_compaction_editing import inputs


def options():
    return dict(expression_version=5,authored_body=True,joint_layout=True,fixed_scope_first=True,
                explicit_edit_scope=True,compact_layout=True,selective_editing=True,prefer_fixed_scope=True)


def edit():return {'claims':[{'claimId':'f','text':'照片生成三维表示。','conditions':{}}]}


def test_preference_uses_only_prose_editor_and_restores_full_readonly_scope_and_metadata():
    report,audits,_=inputs();before=deepcopy((report,audits));joint=Mock();direct=Mock(return_value={'content':json.dumps(edit())})
    out,new=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,**options())
    assert out and out['claims'][1]==report['claims'][1] and new[0]['expression']==audits[0]['expression']
    assert new[0]['verification']=='unchecked' and (report,audits)==before
    for old,row in zip(report['claims'],out['claims']):
        assert all(row[k]==old[k] for k in ('kind','evidenceRefs','obligationIds','detailLevel','tableBindings'))
    prompt=direct.call_args.args[0];rows=json.JSONDecoder().raw_decode(prompt.split('editableClaims：',1)[1])[0]
    readonly=json.JSONDecoder().raw_decode(prompt.split('readonlyContext：',1)[1])[0]
    assert [c['claimId'] for c in rows]==['f'] and readonly[0]['text']==report['claims'][1]['text']
    direct.assert_called_once();joint.assert_not_called()


@pytest.mark.parametrize('mode',['oversize','foreign','readonly_id','blank','truncated','unknown'])
def test_failed_prose_edit_never_changes_scope_or_sends_a_joint_fallback(mode):
    report,audits,_=inputs();response=edit()
    if mode=='oversize':response['claims'][0]['text']='长'*200
    elif mode=='foreign':response['claims'][0]['claimId']='foreign'
    elif mode=='readonly_id':response['claims'].append({'claimId':'c','text':'改写范围。','conditions':{}})
    elif mode=='blank':response['claims'][0]['text']=' '
    direct=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mode=='truncated' else 'stop'});joint=Mock();before=deepcopy((report,audits))
    if mode=='unknown':direct.side_effect=DeepResearchError('call_unknown','Observe the original call')
    if mode=='unknown':
        with pytest.raises(DeepResearchError):compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,**options())
    else:
        out,new=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,**options())
        assert out is None and new==audits
    assert (report,audits)==before;direct.assert_called_once();joint.assert_not_called()


def test_scope_that_cannot_fit_is_routed_to_joint_before_any_prose_call():
    report,audits,response=inputs();expr=deepcopy(audits[0]['expression'])
    expr['observedSettings']=[{'subject':'A','attribute':'评测设置','value':'已有设置说明'*50}]
    report['claims'][1],audit=materialize({**report['claims'][1],'text':'','scopeExpression':expr},5)
    response['claims'][1]['body']['boundary']['observedSettings']=[{'subject':'A','attribute':'评测设置','value':'已有设置'}]
    joint=Mock(return_value={'content':json.dumps(response)});direct=Mock()
    out,new=compact(report,[audit],'100字以内',joint,json.loads,invoke_fixed=direct,**options())
    assert out and new[0]['verification']=='unchecked'
    joint.assert_called_once();direct.assert_not_called()


def test_readonly_accepted_points_consume_capacity_and_are_not_returned_for_edit():
    report,audits,_=inputs();kept=[{'claimId':'kept','kind':'reported','text':'已核实内容。','conditions':{},'evidenceRefs':['kept-source']}]
    before=deepcopy(kept);direct=Mock(return_value={'content':json.dumps(edit())})
    out,_=compact(report,audits,'100字以内',Mock(),json.loads,invoke_fixed=direct,fixed_claims=kept,**options())
    assert out and kept==before and [c['claimId'] for c in out['claims']]==['f','c']
    rows=json.JSONDecoder().raw_decode(direct.call_args.args[0].split('editableClaims：',1)[1])[0]
    assert [c['claimId'] for c in rows]==['f']


def test_old_joint_checkpoint_cannot_silently_select_preferred_route_and_new_one_reuses():
    report,audits,response=inputs();joint=Mock(return_value={'content':json.dumps(response)});direct=Mock(return_value={'content':json.dumps(edit())});states=[]
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'100字以内',joint,json.loads)
    old=options();old.pop('prefer_fixed_scope')
    compact_repairs(*args,checkpoint=states.append,invoke_fixed=direct,**old)
    joint.reset_mock();direct.reset_mock()
    with pytest.raises(DeepResearchError,match='输入不一致'):compact_repairs(*args,saved=states[-1],invoke_fixed=direct,**options())
    joint.assert_not_called();direct.assert_not_called()
    new=[];out=compact_repairs(*args,checkpoint=new.append,invoke_fixed=direct,**options())
    assert out and new[-1]['inputDigest']!=states[-1]['inputDigest'];direct.reset_mock()
    assert compact_repairs(*args,saved=new[-1],invoke_fixed=direct,**options())==out
    joint.assert_not_called();direct.assert_not_called()


def test_unselected_preference_is_byte_exact_to_version_one():
    report,audits,response=inputs();calls=[]
    def joint(prompt):calls.append(prompt);return {'content':json.dumps(response)}
    kwargs=options();kwargs.pop('prefer_fixed_scope');direct=Mock()
    old=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,**kwargs)
    new=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,prefer_fixed_scope=False,**kwargs)
    assert old==new and calls[0]==calls[1];direct.assert_not_called()


@pytest.mark.parametrize('value',[None,0,1,'1'])
def test_preference_requires_boolean_and_selective_contract_before_dispatch(value):
    report,audits,_=inputs();invoke=Mock()
    with pytest.raises(ValueError):compact(report,audits,'100字以内',invoke,json.loads,selective_editing=True,prefer_fixed_scope=value)
    with pytest.raises(ValueError):compact_repairs(report,report['claims'],[],{},'100字以内',invoke,json.loads,selective_editing=True,prefer_fixed_scope=value)
    invoke.assert_not_called()


def test_preference_cannot_be_enabled_without_selective_editing_contract():
    report,audits,_=inputs();invoke=Mock()
    with pytest.raises(ValueError):compact(report,audits,'100字以内',invoke,json.loads,prefer_fixed_scope=True)
    invoke.assert_not_called()


@pytest.mark.parametrize('version',[1,2,3])
@pytest.mark.parametrize('question,preferred',[('100字以内',True),('500字以内',False)])
def test_actual_graph_selects_only_new_route_and_independently_rechecks_all_claims(version,question,preferred):
    from services.deep_research.graph import make_verify_node
    report,audits,response=inputs();initial={'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in report['claims']]}
    record={'question':question,'compactionEditingContractVersion':version,'repairCompactionContractVersion':1,
        'scopeCompactionContractVersion':1,'scopeExpressionContractVersion':5,'scopeExpressionReviewContractVersion':2,
        'reportPresentationContractVersion':2,'factualReasoningContractVersion':10,'answerFormatContractVersion':3,
        'factualPromptContractVersion':3,'authoredBodyContractVersion':1,
        'state':{'outputKind':'claim_verification','reportBody':report,'repairReport':report,'repairAttempted':True,
            'initialVerification':initial,'repairTargets':initial,'initialAnswerCoverage':{'status':'not_requested','gaps':[]},
            'evidence':[],'repairBatchState':{'scopeExpressionAudit':{'0':audits}}}}
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    prompts=[]
    def invoke(rid,node,prompt,options):
        prompts.append(prompt);return {'content':json.dumps(edit() if 'editableClaims：' in prompt else response)}
    verifier=Mock(side_effect=lambda rows,*_: {'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in rows]})
    with patch('services.deep_research.repair.repair_rejected',return_value=report['claims']):
        make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(prompts)==1 and ('editableClaims：' in prompts[0]) is (version in (2,3) and preferred)
    from services.deep_research.compaction_editing import GUIDANCE
    assert (GUIDANCE in prompts[0]) is (version in (1,3) or not preferred)
    assert [c['claimId'] for c in verifier.call_args.args[0]]==['f','c']
    assert record['state']['verifiedReport']['verifiedClaims']==[]
