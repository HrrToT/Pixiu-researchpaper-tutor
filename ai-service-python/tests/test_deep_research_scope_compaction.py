"""Short answers jointly budget facts and recompiled scope without approval."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.scope_compaction import compact, enabled
from services.deep_research.scope_expression import materialize
from services.deep_research.scope_expression_review import context_for_record
from services.deep_research.answer_constraints import visible_count
from test_deep_research_quantified_scope import quantified


def packet():
    raw=quantified();raw['scopeExpression']['observedSettings'][0]['subject']='方法A'
    raw['scopeExpression']['notEstablished'][0]['domain']='其他数据集'
    raw['scopeExpression']['notEstablished'][0]['subject']='方法A'
    raw['obligationIds']=['boundary'];raw['tableBindings']=[]
    scope,audit=materialize(raw,2)
    fact={'claimId':'f','kind':'reported','text':'已有结果。'*70,'conditions':{},
          'evidenceRefs':['own'],'obligationIds':['fact'],'tableBindings':[]}
    report={'claims':[fact,scope],'sections':[{'title':'判断','claimIds':['f']},
                                           {'title':'范围','claimIds':['c']}]}
    expression=deepcopy(raw['scopeExpression'])
    expression['observedSettings'][0].update(attribute='剪枝率',value='66%')
    expression['notEstablished'][0]['predicate']='SSIM绝对差≤0.01'
    response={'claims':[{'claimId':'f','text':'作者报告质量略降。','conditions':{},'scopeExpression':None},
        {'claimId':'c','text':'','conditions':{},'scopeExpression':expression}]}
    return report,[audit],response


def test_joint_edit_keeps_all_points_sources_and_replaces_the_private_ast_atomically():
    report,audits,response=packet();before=deepcopy((report,audits,response))
    invoke=Mock(return_value={'content':json.dumps(response)})
    out,new=compact(report,audits,'只写两点，300字以内',invoke,json.loads,presentation_version=2)
    assert out and visible_count(out,300,presentation_version=2)<=300
    assert [c['claimId'] for c in out['claims']]==['f','c']
    for old,c in zip(report['claims'],out['claims']):
        assert all(c[k]==old[k] for k in ('kind','evidenceRefs','obligationIds','tableBindings'))
    assert new[0]['expression']==response['claims'][1]['scopeExpression']
    assert new[0]['expression']!=audits[0]['expression'] and new[0]['verification']=='unchecked'
    record={'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,
            'state':{'synthesisScopeExpressionAudit':new}}
    assert context_for_record(record,out['claims'])
    assert not context_for_record({**record,'state':{'synthesisScopeExpressionAudit':audits}},out['claims'])
    assert (report,audits,response)==before and invoke.call_count==1
    from services.deep_research.verification import verify_claims
    assert not verify_claims(out['claims'],[])['accepted']


@pytest.mark.parametrize('mutation',[
    'drop','duplicate','extra','order','foreign_ref','free_scope_text','erase_scope',
    'invent_scope','switch_quantifier','drop_boundary','oversize','truncated','stale_audit'])
def test_invalid_compaction_is_atomic_and_never_resends(mutation):
    report,audits,response=packet()
    if mutation=='drop':response['claims'].pop()
    elif mutation=='duplicate':response['claims'].append(deepcopy(response['claims'][0]))
    elif mutation=='extra':response['approval']='passed'
    elif mutation=='order':response['claims'].reverse()
    elif mutation=='foreign_ref':response['claims'][0]['evidenceRefs']=['foreign']
    elif mutation=='free_scope_text':response['claims'][1]['text']='只适用某些情况。'
    elif mutation=='erase_scope':response['claims'][1]['scopeExpression']=None
    elif mutation=='invent_scope':response['claims'][0]['scopeExpression']=response['claims'][1]['scopeExpression']
    elif mutation=='switch_quantifier':response['claims'][1]['scopeExpression']['notEstablished'][0]['quantifier']='exists'
    elif mutation=='drop_boundary':response['claims'][1]['scopeExpression']['notEstablished']=[]
    elif mutation=='oversize':response['claims'][0]['text']='长'*400
    elif mutation=='stale_audit':audits[0]['renderedText']='其他文本'
    before=deepcopy((report,audits))
    invoke=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mutation=='truncated' else 'stop'})
    out,new=compact(report,audits,'300字以内',invoke,json.loads,presentation_version=2)
    assert out is None and new==audits and (report,audits)==before
    assert invoke.call_count==(0 if mutation=='stale_audit' else 1)


def test_within_limit_requires_no_edit_or_call():
    report,audits,_=packet();invoke=Mock()
    out,new=compact(report,audits,'1000字以内',invoke,json.loads,presentation_version=2)
    assert out==report and new==audits
    invoke.assert_not_called()


@pytest.mark.parametrize('mutation',['missing_id','duplicate_id','list_id','empty_id','non_object',
                                    'missing_text','invalid_conditions','invalid_audit','invalid_report'])
def test_malformed_model_or_audit_input_is_rejected_before_calling(mutation):
    report,audits,_=packet()
    if mutation=='missing_id':report['claims'][0].pop('claimId')
    elif mutation=='duplicate_id':report['claims'].append(deepcopy(report['claims'][0]))
    elif mutation=='list_id':report['claims'][0]['claimId']=[]
    elif mutation=='empty_id':report['claims'][0]['claimId']=' '
    elif mutation=='non_object':report['claims'][0]='bad row'
    elif mutation=='missing_text':report['claims'][0].pop('text')
    elif mutation=='invalid_conditions':report['claims'][0]['conditions']=42
    elif mutation=='invalid_audit':audits[0]=None
    else:report={'claims':None}
    before=deepcopy((report,audits));invoke=Mock()
    assert compact(report,audits,'300字以内',invoke,json.loads)==(None,audits)
    assert (report,audits)==before
    invoke.assert_not_called()


def test_actual_synthesis_stores_compacted_scope_and_checks_the_actual_new_text():
    from services.deep_research.graph import make_synthesize_node
    report,audits,response=packet()
    initial=deepcopy(report)
    initial['claims'][1].update(text='',scopeExpression=audits[0]['expression'])
    record={'question':'只写两点，300字以内','scopeExpressionContractVersion':2,
        'scopeCompactionContractVersion':1,'scopeExpressionReviewContractVersion':2,
        'reportPresentationContractVersion':2,
        'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_id,mutate,**kw):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    calls=[]
    def invoke(_id,node,prompt,options,**kwargs):
        calls.append(node)
        return {'content':json.dumps(initial if node=='synthesize' else response)}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert 'error_code' not in result and calls==['synthesize','synthesize_compact']
    state=record['state'];claims=state['reportBody']['claims']
    assert state['synthesisScopeExpressionAudit'][0]['expression']==response['claims'][1]['scopeExpression']
    assert context_for_record(record,claims)['c']['notEstablished'][0] in claims[1]['text']
    assert visible_count(state['reportBody'],300,presentation_version=2)<=300


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_new_policy_is_server_owned_immutable_and_absent_from_legacy_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'first','question':'核查',
            'deferStart':True,'scopeCompactionContractVersion':replacement},start_async=False)
        assert enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'scopeCompactionContractVersion':replacement})
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('scopeCompactionContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        assert not enabled(before)
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()
