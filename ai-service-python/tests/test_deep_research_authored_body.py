from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.authored_body import decode,enabled,required_scope_ids
from services.deep_research.scope_expression import materialize
from services.deep_research.draft_validation import materialize_claims,verification_inputs,reject_initial


def expression():return {'observedSettings':[],'notEstablished':[{'type':'comparison_evidence','subjects':['A','B'],'quantity':'显存'}]}
def boundary(cid='c'):
    return {'claimId':cid,'kind':'inference','body':{'boundary':expression()},'evidenceRefs':['a','b'],'obligationIds':['o'],'detailLevel':'fulltext','tableBindings':[]}
def prose(cid='f'):
    return {'claimId':cid,'kind':'reported','body':{'prose':{'text':'照片用于生成三维表示。','conditions':{}}},'evidenceRefs':['a'],'obligationIds':['o'],'detailLevel':'fulltext','tableBindings':[]}
def evidence():
    from services.deep_research.verification import make_evidence
    return [make_evidence({'workId':k,'versionId':k+'-v1','contentHash':k,'accessLevel':'fulltext'},
        'We describe the evaluated method on GPU A100.','We describe the evaluated method on GPU A100.',location={'page':1},obligation_ids=['o']) | {'evidenceId':k,'sourceId':k,'sourceTitle':k} for k in ('a','b')]


def test_exclusive_body_compiles_to_existing_unverified_schema_without_changing_authoring_data():
    raw=boundary();before=deepcopy(raw);canonical=decode(raw);compiled,audit=materialize(canonical,5)
    assert compiled['text']=='当前引用不足以比较A与B的显存。' and audit['verification']=='unchecked'
    assert 'body' not in compiled and 'scopeExpression' not in compiled and raw==before
    ordinary=decode(prose());assert ordinary['text']==prose()['body']['prose']['text'] and ordinary['conditions']=={}
    from services.deep_research.verification import verify_claims
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Fixture insufficient semantic support'}])
    assert not verify_claims([compiled],evidence(),checker)['accepted']
    checker.assert_called_once()


@pytest.mark.parametrize('mutation',['top_text','top_conditions','top_scope','both','unknown','bad_prose','wrong_kind'])
def test_conflicting_or_unknown_bodies_are_rejected_instead_of_choosing_a_form(mutation):
    raw=boundary()
    if mutation=='top_text':raw['text']='作者从未报告显存。'
    elif mutation=='top_conditions':raw['conditions']={}
    elif mutation=='top_scope':raw['scopeExpression']=None
    elif mutation=='both':raw['body']['prose']=prose()['body']['prose']
    elif mutation=='unknown':raw['body']={'other':{}}
    elif mutation=='bad_prose':raw=prose();raw['body']['prose']['conditions']=[]
    else:raw['kind']='reported'
    before=deepcopy(raw)
    with pytest.raises(ValueError):decode(raw)
    assert raw==before


@pytest.mark.parametrize('invalid',[False,True])
def test_actual_initial_synthesis_compiles_valid_points_and_isolates_a_bad_body(invalid):
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node
    _,_,record=node_capture(3)
    record.update(authoredBodyContractVersion=1,scopeExpressionContractVersion=5,draftValidationContractVersion=1)
    rows=[prose(),boundary()]
    for row in rows:row['evidenceRefs']=['E1'];row['obligationIds']=['o']
    if invalid:rows[1]['body']['prose']={'text':'作者从未报告显存。','conditions':{}}
    raw=deepcopy(rows);sent=[]
    def update(rid,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append(prompt);assert node=='synthesize'
        assert 'Each claim has exactly: claimId,kind,evidenceRefs,obligationIds,detailLevel,tableBindings,body.' in prompt
        assert 'body.boundary=' in prompt and 'Other points use body.prose' in prompt
        return {'content':json.dumps({'sections':[{'title':'结果','claimIds':['f','c']}],'claims':rows})}
    out=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert not out.get('error_code') and len(sent)==1 and rows==raw
    saved=record['state'];assert saved['reportBody']['claims'][0]['text']==prose()['body']['prose']['text']
    audit=saved['draftValidationAudit']
    if invalid:
        assert audit['rejected'][0]['reason']=='invalid_authored_body'
        original=audit['rejected'][0]['originalClaim']
        assert {k:v for k,v in original.items() if k!='evidenceRefs'}=={k:v for k,v in raw[1].items() if k!='evidenceRefs'}
        assert all(ref in {e['evidenceId'] for e in record['state']['evidence']} for ref in original['evidenceRefs'])
        assert [c['claimId'] for c in verification_inputs(saved['reportBody']['claims'],audit)]==['f']
        assert [c['claimId'] for c in reject_initial({'accepted':saved['reportBody']['claims'],'rejected':[]},audit)['accepted']]==['f']
        assert required_scope_ids(saved,saved['reportBody'])==['c']
    else:
        assert not audit['rejected'] and saved['synthesisScopeExpressionAudit'][0]['verification']=='unchecked'


def options():return {'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,'compact_source_repair':True,
    'factual_prompt_version':3,'scope_expression':5,'claim_check':9,'required_scope_ids':['c'],'authored_body':True,
    'requirement_context':[{'obligationId':'o','question':'比较A和B的显存','requiredSources':['a','b']}]}


@pytest.mark.parametrize('downgrade',[False,True])
def test_actual_repair_requires_body_boundary_restores_aliases_and_reuses_completed_checkpoint(downgrade):
    from services.deep_research.repair import repair_rejected
    from services.deep_research.contracts import DeepResearchError
    canonical,_=materialize(decode(boundary()),5);report={'claims':[canonical]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    raw=boundary();raw['evidenceRefs']=['E1','E2']
    if downgrade:raw['body']={'prose':{'text':'当前引用的GPU为A100。','conditions':{}}}
    invoke=Mock(return_value={'content':json.dumps([raw])});states=[]
    result=repair_rejected(report,checks,evidence(),'比较A和B的显存',invoke,json.loads,checkpoint=states.append,**options())
    assert bool(result) is (not downgrade) and invoke.call_count==1
    assert 'choose body.boundary' in invoke.call_args.args[0]
    if result:assert result[0]['evidenceRefs']==['a','b'] and 'body' not in result[0]
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(report,checks,evidence(),'比较A和B的显存',invoke,json.loads,batch_state=saved,**options())==result
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,evidence(),'比较A和B的显存',invoke,json.loads,batch_state=saved,**{**options(),'authored_body':False})
    invoke.assert_not_called()


@pytest.mark.parametrize('retained',[False,True])
def test_declared_removals_cannot_edit_or_hide_unsupported_operator_content(retained):
    from services.deep_research.repair import repair_rejected
    negative='作者从未报告显存'
    original={**decode(prose('c')),'kind':'inference','text':negative+'。','evidenceRefs':['a','b']}
    raw=boundary();raw['evidenceRefs']=['E1','E2'];raw['discardedDraftSpans']=[negative]
    if retained:raw['body']['boundary']['notEstablished'][0]['quantity']=negative
    result=repair_rejected({'claims':[original]},{'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},evidence(),'比较A和B的显存',Mock(return_value={'content':json.dumps([raw])}),json.loads,target_goals=5,**options())
    assert bool(result) is (not retained)
    if result:assert negative not in result[0]['text'] and result[0]['text'].startswith('当前引用不足')


@pytest.mark.parametrize('change',[None,'downgrade','both','quantity'])
def test_compaction_compiles_one_branch_and_preserves_scope_identity(change):
    from services.deep_research.scope_compaction import compact
    scope,audit=materialize(decode(boundary()),5);fact=decode(prose());fact.pop('scopeExpression');fact['text']='长说明。'*100
    body={'boundary':expression()}
    if change=='downgrade':body={'prose':{'text':'直接认为论文没有报告。','conditions':{}}}
    elif change=='both':body['prose']={'text':'第二种内容。','conditions':{}}
    elif change=='quantity':body['boundary']['notEstablished'][0]['quantity']='训练耗时'
    response={'claims':[{'claimId':'f','body':{'prose':{'text':'照片生成三维表示。','conditions':{}}}},{'claimId':'c','body':body}]}
    invoke=Mock(return_value={'content':json.dumps(response)})
    result,after=compact({'claims':[fact,scope]},[audit],'100字以内',invoke,json.loads,expression_version=5,authored_body=True)
    assert bool(result) is (change is None) and invoke.call_count==1
    if result:assert result['claims'][1]==scope and after[0]['verification']=='unchecked'


@pytest.mark.parametrize('change',[False,True])
def test_audience_polish_cannot_invalidate_compiled_scope_and_cannot_change_checkpoint_identity(change):
    from services.deep_research.audience_rewrite import rewrite_for_beginner
    from services.deep_research.contracts import DeepResearchError
    scope,_=materialize(decode(boundary()),5);fact=decode(prose());fact.pop('scopeExpression');report={'claims':[fact,scope]}
    patches={'claims':[{'claimId':c['claimId'],'text':c['text'],'conditions':c['conditions']} for c in report['claims']]}
    patches['claims'][0]['text']='用照片得到三维模型。'
    if change:patches['claims'][1]['text']='两篇论文都没有报告显存。'
    invoke=Mock(return_value={'content':json.dumps(patches)});states=[]
    result=rewrite_for_beginner(report,evidence(),'用通俗语言解释，1000字以内',invoke,json.loads,contract_version=9,protected_claim_ids=['c'],checkpoint=states.append)
    assert result['claims'][1]==scope
    if change:assert result==report and states[-1]['editReason']=='structured_scope_changed'
    else:assert result['claims'][0]['text']==patches['claims'][0]['text']
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert rewrite_for_beginner(report,evidence(),'用通俗语言解释，1000字以内',invoke,json.loads,contract_version=9,protected_claim_ids=['c'],saved_state=saved)==result
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):rewrite_for_beginner(report,evidence(),'用通俗语言解释，1000字以内',invoke,json.loads,contract_version=9,saved_state=saved)
    invoke.assert_not_called()


@pytest.mark.parametrize('client_value',[None,True,0,2])
def test_body_contract_is_server_owned_immutable_and_not_added_to_legacy_runs(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较论文','deferStart':True,'authoredBodyContractVersion':client_value},start_async=False)
        assert r['authoredBodyContractVersion']==1 and enabled(r,'paper_comparison')
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'authoredBodyContractVersion':client_value})
        old=deepcopy(r);old.update(runId='legacy',idempotencyKey='old');old.pop('authoredBodyContractVersion');repo.create_run(old)
        before=repo.require_run('legacy');facade.create({'workspaceTaskId':'t','operationKey':'next','question':'比较论文','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before and not enabled(before,'paper_comparison')
        assert not enabled(r,'experiment_design')
    finally:facade.shutdown()


def test_invalid_mixed_body_can_be_rebuilt_without_losing_the_original_or_choosing_a_branch():
    from services.deep_research.repair import repair_rejected
    bad=boundary();negative='作者从未报告显存';bad['body']['prose']={'text':negative+'。','conditions':{}}
    before=deepcopy(bad);fresh=boundary();fresh['evidenceRefs']=['E1','E2'];fresh['discardedDraftSpans']=[negative]
    states=[]
    result=repair_rejected({'claims':[bad]},{'accepted':[],'rejected':[{'claimId':'c','reason':'invalid_authored_body'}]},evidence(),'比较A和B的显存',Mock(return_value={'content':json.dumps([fresh])}),json.loads,target_goals=5,checkpoint=states.append,**options())
    assert result and result[0]['text']=='当前引用不足以比较A与B的显存。' and bad==before
    assert states[-1]['scopeExpressionAudit']['0'][0]['verification']=='unchecked'


def test_repair_compaction_checkpoint_is_bound_to_the_authoring_protocol():
    from services.deep_research.repair_compaction import compact_repairs
    from services.deep_research.contracts import DeepResearchError
    scope,audit=materialize(decode(boundary()),5);fact=decode(prose());fact.pop('scopeExpression');fact['text']='已有说明。'*100
    report={'claims':[fact,scope]};batch={'scopeExpressionAudit':{'0':[audit]}}
    response={'claims':[{'claimId':'f','body':{'prose':{'text':'照片生成三维表示。','conditions':{}}}},{'claimId':'c','body':{'boundary':expression()}}]}
    invoke=Mock(return_value={'content':json.dumps(response)});states=[]
    kwargs={'expression_version':5,'authored_body':True}
    result=compact_repairs(report,report['claims'],[],batch,'100字以内',invoke,json.loads,checkpoint=states.append,**kwargs)
    assert result and result[1]==scope
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert compact_repairs(report,report['claims'],[],batch,'100字以内',invoke,json.loads,saved=saved,**kwargs)==result
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):compact_repairs(report,report['claims'],[],batch,'100字以内',invoke,json.loads,saved=saved,expression_version=5)
    invoke.assert_not_called()
