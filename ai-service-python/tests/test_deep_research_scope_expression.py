from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.scope_expression import materialize,GUIDANCE,enabled
from services.deep_research.answer_constraints import compact_answer
from services.deep_research.repair import repair_rejected
from services.deep_research.verification import verify_claims
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_redraft import inputs


def claim():
    return {'claimId':'c','kind':'inference','text':'','conditions':{},'evidenceRefs':['e'],
        'scopeExpression':{'observedSettings':[{'subject':'方法A','attribute':'剪枝率','value':'66%'}],
                           'notEstablished':['所有场景和指标均无损']}}


def test_authored_operators_render_observations_and_epistemic_limit_not_exclusivity():
    value=claim();before=deepcopy(value);row,audit=materialize(value)
    assert row['text']=='所引来源报告的评估设置包括：方法A，剪枝率=66%。这些引用不足以证明：所有场景和指标均无损。'
    assert row['kind']==value['kind'] and row['evidenceRefs']==value['evidenceRefs']
    assert 'scopeExpression' not in row and audit['expression']==value['scopeExpression']
    assert audit['verification']=='unchecked' and value==before
    assert '只有' not in row['text'] and '未验证' not in row['text']


@pytest.mark.parametrize('change',[{'text':'只有这些条件才成立。'},{'conditions':{'scope':'仅适用某场景'}},
    {'kind':'reported'},{'kind':'proposal'},{'scopeExpression':{}},
    {'scopeExpression':{'observedSettings':[],'notEstablished':[]}},
    {'scopeExpression':{'observedSettings':[],'notEstablished':[True]}},
    {'scopeExpression':{'observedSettings':[{'subject':'A','attribute':'ratio','value':66}], 'notEstablished':[]}}])
def test_conflicting_prose_invalid_kinds_and_missing_values_are_rejected_not_repaired(change):
    value={**claim(),**change};before=deepcopy(value)
    with pytest.raises(ValueError):materialize(value)
    assert value==before


def test_empty_ordinary_expression_does_not_rewrite_prose_or_require_a_new_kind():
    value={'claimId':'c','text':'作者报告的结果。','kind':'reported','scopeExpression':None}
    row,audit=materialize(value)
    assert row=={k:v for k,v in value.items() if k!='scopeExpression'} and audit is None
    assert materialize(row)==(row,None)


def test_compaction_only_rewrites_other_points_and_preserves_compiled_scope_and_limit():
    scope,_=materialize(claim());fact={'claimId':'f','kind':'reported','text':'甲'*100,'conditions':{},'evidenceRefs':[]}
    report={'claims':[fact,scope]};before=deepcopy(report)
    invoke=Mock(return_value={'content':json.dumps({'claims':[{'claimId':'f','text':'保留原事实。','conditions':{}}]})})
    result=compact_answer(report,'100字以内',invoke,json.loads,preserve_claims=True,
        presentation_version=2,output_kind='claim_verification',fixed_claim_ids=['c'])
    assert result and result['claims'][1]==scope and report==before
    prompt=invoke.call_args.args[0];targets=json.loads(prompt.split('输入：',1)[1])
    assert [r['claimId'] for r in targets]==['f'] and '固定范围说明（只读' in prompt
    assert invoke.call_count==1
    invoke.reset_mock()
    assert compact_answer({'claims':[scope]},'20字以内',invoke,json.loads,
                          presentation_version=2,fixed_claim_ids=['c']) is None
    invoke.assert_not_called()


def test_compaction_cannot_rewrite_a_fixed_operator_by_echoing_its_identity():
    scope,_=materialize(claim());fact={'claimId':'f','kind':'reported','text':'甲'*100,'conditions':{}}
    invoke=Mock(return_value={'content':json.dumps({'claims':[{'claimId':'c','text':'只有此设置才成立。'}]})})
    assert compact_answer({'claims':[fact,scope]},'100字以内',invoke,json.loads,
                          presentation_version=2,fixed_claim_ids=['c']) is None
    assert invoke.call_count==1


def test_actual_synthesis_compiles_before_verification_and_keeps_private_audit():
    from services.deep_research.graph import make_synthesize_node
    c=claim();c['evidenceRefs']=[]
    record={'scopeExpressionContractVersion':1,'question':'解释条件和范围，200字以内',
            'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps({'claims':[c]})})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert 'error_code' not in result and GUIDANCE in invoke.call_args.args[2]
    assert record['state']['reportBody']['claims'][0]['text']==materialize(c)[0]['text']
    assert record['state']['synthesisScopeExpressionAudit'][0]['verification']=='unchecked'
    # No evidence: rendered operators cannot approve themselves.
    assert not verify_claims(record['state']['reportBody']['claims'],[])['accepted']


def test_actual_synthesis_rejects_conflicting_text_instead_of_quietly_weakening_it():
    from services.deep_research.graph import make_synthesize_node
    c=claim();c['text']='只有这个设置才成立。'
    record={'scopeExpressionContractVersion':1,'question':'解释范围','state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps({'claims':[c]})})
    assert make_synthesize_node(invoke,update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
    assert invoke.call_count==1 and 'reportBody' not in record['state']


def test_actual_verification_passes_scope_contract_and_retains_a_rejected_candidate(monkeypatch):
    from services.deep_research.graph import make_verify_node
    c,e,check,requirements=inputs();c['kind']='inference'
    record={'scopeExpressionContractVersion':1,'factRedraftContractVersion':3,
        'state':{'outputKind':'claim_verification','reportBody':{'claims':[c]},'evidence':[e],
                 'plan':[{'itemId':'i','obligations':requirements}]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'not_requested','gaps':[]})
    value=claim();value['evidenceRefs']=['E1'];seen=[]
    def invoke(_id,node,prompt,options):
        assert node=='repair_claims' and GUIDANCE in prompt;seen.append(prompt)
        return {'content':json.dumps([value])}
    make_verify_node(Mock(return_value=check),None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(seen)==1 and record['state']['repairBatchState']['scopeExpressionAudit']['0'][0]['verification']=='unchecked'
    assert not record['state']['verifiedReport']['verifiedClaims']


def test_repair_renders_exact_authored_expression_then_reuses_without_resending_and_still_requires_support():
    c,e,check,requirements=inputs();c['kind']='inference';states=[]
    value=claim();value['evidenceRefs']=['E1']
    invoke=Mock(return_value={'content':json.dumps([value])})
    kw=dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,
        requirement_context=requirements,scope_expression=True)
    result=repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,
        checkpoint=lambda s:states.append(deepcopy(s)),**kw)
    assert result and result[0]['text']==materialize(value)[0]['text']
    assert result[0]['evidenceRefs']==c['evidenceRefs'] and 'scopeExpression' not in result[0]
    assert states[-1]['scopeExpressionAudit']['0'][0]['expression']==value['scopeExpression']
    assert repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,batch_state=states[-1],**kw)==result
    assert invoke.call_count==1
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Pruning observation is not in this source'}])
    assert not verify_claims(result,[e],semantic)['accepted']
    kw['scope_expression']=False
    with pytest.raises(DeepResearchError):
        repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,batch_state=states[-1],**kw)
    assert invoke.call_count==1


@pytest.mark.parametrize('replacement',[None,0,True,'1',1,2,3,5])
def test_policy_is_server_owned_immutable_and_not_added_to_old_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
                         'scopeExpressionContractVersion':replacement},start_async=False)
        assert enabled(r) and r['scopeExpressionContractVersion']==4
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda v:{**v,'scopeExpressionContractVersion':replacement})
        old=deepcopy(r);old.update(runId='legacy',idempotencyKey='legacy');old.pop('scopeExpressionContractVersion')
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before and not enabled(before)
    finally:facade.shutdown()
