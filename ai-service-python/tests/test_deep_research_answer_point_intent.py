from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.answer_point_intent import enabled,from_drafting_audit,repair_guidance,GUIDANCE
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.verification import verify_claims
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_redraft import inputs


def context():
    return {'c':{'scopeDecision':'bounded_inference','unresolved':'只讨论已读证据支持的范围；其他场景尚未建立。'}}


def test_only_original_factual_point_scope_intent_is_copied_without_rejected_prose_or_observations():
    c,e,checks,requirements=inputs()
    audit={'c':{**context()['c'],'observations':[{'quote':'REJECTED_SOURCE_ASSERTION'}],
                'text':'REJECTED_PROSE','extra':'IGNORE'},'other':context()['c']}
    before=deepcopy((audit,c))
    assert from_drafting_audit(audit,[c])==context()
    assert (audit,c)==before
    assert from_drafting_audit(audit,[{**c,'kind':'hypothesis'}])=={}
    for malformed in [None,True,{'c':None},{'c':{'scopeDecision':'made_up','unresolved':'x'}}]:
        assert from_drafting_audit(malformed,[c])=={}


def test_new_context_preserves_target_question_without_copying_rejected_text_and_does_not_change_legacy_prompt():
    c,e,check,requirements=inputs();before=deepcopy((c,e,check,requirements))
    kwargs=dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,requirement_context=requirements)
    old=_prepare_repair({'claims':[c]},check,[e],'解释范围',**kwargs)
    new=_prepare_repair({'claims':[c]},check,[e],'解释范围',answer_intents=context(),**kwargs)
    assert c['text'] not in new['prompt'] and c['conditions']['scope'] not in new['prompt']
    assert context()['c']['unresolved'] in new['prompt'] and 'UNVERIFIED drafting metadata' in new['prompt']
    assert e['quote'] in new['prompt'] and requirements[0]['question'] in new['prompt']
    assert old['originals']==new['originals'] and old['allowed']==new['allowed'] and old['aliases']==new['aliases']
    assert 'Unverified point intentions' not in old['prompt']
    assert _prepare_repair({'claims':[c]},check,[e],'解释范围',**kwargs)['prompt']==old['prompt']
    assert (c,e,check,requirements)==before


def test_context_never_crosses_targets_or_becomes_a_permission():
    text=repair_guidance({**context(),'other':{'unresolved':'OTHER_TARGET_SECRET'}},{'c'})
    assert context()['c']['unresolved'] in text and 'OTHER_TARGET_SECRET' not in text
    assert 'grant no support, source permission' in text and 'omit the target' in text


def test_revision_is_durable_and_context_identity_cannot_change_on_resume():
    c,e,check,requirements=inputs();states=[]
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','kind':'reported',
        'text':'网络预测平移和旋转。','conditions':{},'evidenceRefs':['E1'],'detailLevel':'fulltext'}])})
    kwargs=dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,
                requirement_context=requirements,answer_intents=context())
    rows=repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,
                         checkpoint=lambda s:states.append(deepcopy(s)),**kwargs)
    assert invoke.call_count==1 and rows
    assert 'answer_intents' not in rows[0] and 'scopeDecision' not in rows[0]
    assert repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,batch_state=states[-1],**kwargs)==rows
    assert invoke.call_count==1
    kwargs['answer_intents']={'c':{'scopeDecision':'bounded_inference','unresolved':'Changed context'}}
    with pytest.raises(DeepResearchError):
        repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,batch_state=states[-1],**kwargs)
    assert invoke.call_count==1
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Unsupported remaining scope'}])
    assert not verify_claims(rows,[e],semantic)['accepted']


def test_actual_synthesis_adds_guidance_only_for_new_enabled_factual_paths():
    from services.deep_research.graph import make_synthesize_node
    for marker in (None,0,True,'1',1):
        record={'answerPointIntentContractVersion':marker,'question':'核查范围，200字以内',
                'state':{'outputKind':'claim_verification','evidence':[]}}
        def update(_rid,mutate,**kwargs):
            nonlocal record
            record=mutate(deepcopy(record));return deepcopy(record)
        llm=Mock(return_value={'content':'','finishReason':'length'})
        assert make_synthesize_node(llm,update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
        assert (GUIDANCE in llm.call_args.args[2]) is (type(marker) is int and marker==1)


@pytest.mark.parametrize('marker',[None,True,'1',1])
def test_actual_verify_node_passes_initial_private_point_intent_only_for_enabled_runs(marker,monkeypatch):
    from services.deep_research.graph import make_verify_node
    c,e,check,requirements=inputs()
    record={'answerPointIntentContractVersion':marker,'factRedraftContractVersion':3,
        'state':{'outputKind':'claim_verification','reportBody':{'claims':[c]},'evidence':[e],
            'factualDraftingAudit':context(),'plan':[{'itemId':'i','obligations':requirements}]}}
    def update(_rid,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'not_requested','gaps':[]})
    seen=[]
    def invoke(_rid,node,prompt,options):
        assert node=='repair_claims';seen.append(prompt)
        assert (context()['c']['unresolved'] in prompt) is (type(marker) is int and marker==1)
        assert c['text'] not in prompt
        return {'content':'[]'}
    make_verify_node(Mock(return_value=check),None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(seen)==1 and record['state']['repairReport']['claims'][0]['text']==c['text']
    assert not record['state']['verifiedReport']['verifiedClaims']


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_policy_is_server_owned_and_immutable_without_migrating_old_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'answerPointIntentContractVersion':replacement},start_async=False)
        assert r['answerPointIntentContractVersion']==1 and enabled(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda v:{**v,'answerPointIntentContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('answerPointIntentContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'核查','deferStart':True},start_async=False)
        assert repo.require_run('old')==before and not enabled(before)
    finally:facade.shutdown()
