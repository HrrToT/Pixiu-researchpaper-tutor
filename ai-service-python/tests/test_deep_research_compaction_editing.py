"""Selective wording edits retain IDs, source permissions and fresh verification."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.authored_body import decode
from services.deep_research.compaction_editing import HEADER,GUIDANCE,REPLACEMENT
from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.scope_compaction import compact
from services.deep_research.scope_expression import materialize
from test_deep_research_authored_body import boundary,prose,expression,evidence


def inputs():
    scope,audit=materialize(decode(boundary()),5)
    fact=decode(prose());fact.pop('scopeExpression');fact['text']='已有说明。'*100
    report={'claims':[fact,scope]}
    response={'claims':[{'claimId':'f','body':{'prose':{'text':'照片生成三维表示。','conditions':{}}}},
                        {'claimId':'c','body':{'boundary':expression()}}]}
    return report,[audit],response


def test_rewrite_permission_removes_conflicting_instruction_without_editing_data_or_approving_facts():
    report,audits,response=inputs();report['claims'][0]['text']+=HEADER
    before=deepcopy((report,audits));invoke=Mock(return_value={'content':json.dumps(response)})
    out,new=compact(report,audits,'100字以内',invoke,json.loads,expression_version=5,
        authored_body=True,joint_layout=True,budget_guidance=True,selective_editing=True)
    assert out and new[0]['verification']=='unchecked'
    prompt=invoke.call_args.args[0];instructions,data=prompt.split('\nInput:\n',1)
    assert HEADER not in instructions and GUIDANCE in instructions
    assert json.loads(data)[0]['text']==report['claims'][0]['text']
    assert out['claims'][1]==report['claims'][1]
    for old,row in zip(report['claims'],out['claims']):
        assert all(row[k]==old[k] for k in ('kind','evidenceRefs','obligationIds','detailLevel','tableBindings'))
    assert (report,audits)==before and invoke.call_count==1
    from services.deep_research.verification import verify_claims
    result=verify_claims(out['claims'],evidence(),lambda rows,_:[{'claimId':c['claimId'],'status':'failed','reason':'Source support unresolved'} for c in rows])
    assert not result['accepted']


@pytest.mark.parametrize('mutation',['oversize','drop_point','blank','foreign','quantity','subject','drop_boundary','truncated'])
def test_editing_permission_never_relaxes_compiled_length_identity_or_frozen_scope(mutation):
    report,audits,response=inputs()
    if mutation=='oversize':response['claims'][0]['body']['prose']['text']='长'*200
    elif mutation=='drop_point':response['claims'].pop()
    elif mutation=='blank':response['claims'][0]['body']['prose']['text']=' '
    elif mutation=='foreign':response['claims'][0]['evidenceRefs']=['foreign']
    elif mutation=='quantity':response['claims'][1]['body']['boundary']['notEstablished'][0]['quantity']='速度'
    elif mutation=='subject':response['claims'][1]['body']['boundary']['notEstablished'][0]['subjects']=['A','foreign']
    elif mutation=='drop_boundary':response['claims'][1]['body']['boundary']['notEstablished']=[]
    invoke=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mutation=='truncated' else 'stop'})
    out,new=compact(report,audits,'100字以内',invoke,json.loads,expression_version=5,
        authored_body=True,joint_layout=True,budget_guidance=True,selective_editing=True)
    assert out is None and new==audits and invoke.call_count==1


def test_default_and_explicit_off_keep_legacy_prompt_result_and_checkpoint_identity_exact():
    report,audits,response=inputs();calls=[]
    def invoke(prompt):calls.append(prompt);return {'content':json.dumps(response)}
    kwargs={'expression_version':5,'authored_body':True,'joint_layout':True,'budget_guidance':True}
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'100字以内',invoke,json.loads)
    states=[];old=compact_repairs(*args,checkpoint=states.append,**kwargs)
    legacy=deepcopy(states[-1]);same=[];actual=compact_repairs(*args,checkpoint=same.append,selective_editing=False,**kwargs)
    assert old==actual and calls[0]==calls[1] and states[-1]['inputDigest']==same[-1]['inputDigest']
    assert HEADER in calls[0] and GUIDANCE not in calls[0]
    with pytest.raises(DeepResearchError,match='输入不一致'):
        compact_repairs(*args,saved=legacy,selective_editing=True,**kwargs)
    assert len(calls)==2


def test_completed_new_edit_checkpoint_reuses_without_another_model_request():
    report,audits,response=inputs();invoke=Mock(return_value={'content':json.dumps(response)});states=[]
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'100字以内',invoke,json.loads)
    kwargs={'expression_version':5,'authored_body':True,'joint_layout':True,'budget_guidance':True,'selective_editing':True}
    out=compact_repairs(*args,checkpoint=states.append,**kwargs);invoke.reset_mock()
    assert compact_repairs(*args,saved=states[-1],**kwargs)==out
    invoke.assert_not_called()


@pytest.mark.parametrize('bad',[None,0,1,'1'])
def test_policy_type_errors_stop_before_dispatch(bad):
    report,audits,_=inputs();invoke=Mock()
    with pytest.raises(ValueError):compact(report,audits,'100字以内',invoke,json.loads,selective_editing=bad)
    with pytest.raises(ValueError):compact_repairs(report,report['claims'],[],{},'100字以内',invoke,json.loads,selective_editing=bad)
    invoke.assert_not_called()


def test_quoted_instruction_in_human_question_is_not_rewritten_or_treated_as_server_policy():
    report,audits,response=inputs();invoke=Mock(return_value={'content':json.dumps(response)})
    question='100字以内，解释这段话：'+HEADER
    out,_=compact(report,audits,question,invoke,json.loads,expression_version=5,authored_body=True,
                  joint_layout=True,selective_editing=True)
    assert out and question in invoke.call_args.args[0] and REPLACEMENT in invoke.call_args.args[0]


@pytest.mark.parametrize('value',[1,True,None])
def test_actual_graph_selects_new_policy_only_for_strict_version_and_rechecks_edits(value):
    from unittest.mock import patch
    from services.deep_research.graph import make_verify_node
    from test_deep_research_scope_compaction import packet
    report,audits,response=packet();report['sections']=[]
    kept={'claimId':'kept','kind':'reported','text':'保留。','conditions':{},'evidenceRefs':['e']}
    initial={'accepted':[kept],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in report['claims']]}
    record={'question':'300字以内','compactionEditingContractVersion':value,'repairCompactionContractVersion':1,
        'scopeCompactionContractVersion':1,'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,'reportPresentationContractVersion':2,
        'state':{'outputKind':'claim_verification','reportBody':report,'repairReport':report,'repairAttempted':True,
            'initialVerification':initial,'repairTargets':initial,'initialAnswerCoverage':{'status':'not_requested','gaps':[]},
            'evidence':[],'repairBatchState':{'scopeExpressionAudit':{'0':audits}}}}
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(response)})
    verifier=Mock(side_effect=lambda rows,*_: {'accepted':[],'rejected':[{'claimId':c['claimId'],'reason':'semantic_unresolved'} for c in rows]})
    with patch('services.deep_research.repair.repair_rejected',return_value=report['claims']):
        make_verify_node(verifier,None,update,llm_invoke=invoke)({'run_id':'r'})
    assert invoke.call_count==1
    assert (GUIDANCE in invoke.call_args.args[2]) is (type(value) is int and value==1)
    assert [c['claimId'] for c in verifier.call_args.args[0]]==['f','c']
    assert record['state']['verifiedReport']['verifiedClaims']==[kept]


def test_root_edit_policy_is_server_owned_immutable_and_never_added_to_legacy_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    key='compactionEditingContractVersion';repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',key:False},start_async=False)
        assert type(row[key]) is int and row[key]==3
        old=deepcopy(row);old.pop(key);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        for rid in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,key:4})
        assert key not in repo.require_run('old')
    finally:facade.shutdown()
