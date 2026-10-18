from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, UnknownCallError
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_verify_node
from services.deep_research.repair import repair_rejected
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.verification import verify_claims
from test_deep_research_quantity_words import setup


def inputs():
    c,e=setup('BAD_DRAFT_MUST_NOT_BE_COPIED', 'The network predicts translation and rotation.')
    c['conditions']={'scope':'BAD_CONDITION_MUST_NOT_BE_COPIED'};c['obligationIds']=['o']
    check={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved',
        'detail':'Only the actual output roles are established.'}]}
    requirements=[{'obligationId':'o','question':'Explain the output roles',
        'completionCriteria':[{'criterionId':'roles','requirement':'Explain the output roles','responseType':'explanation'}]}]
    return c,e,check,requirements


@pytest.mark.parametrize('redraft',[False,True])
def test_generation_view_changes_without_erasing_the_audit_or_original_citations(redraft):
    c,e,check,requirements=inputs();before=deepcopy([c,e,check]);saved=[]
    def invoke(prompt):
        targets=json.JSONDecoder().raw_decode(prompt.split('Rejected claims and checks:\n',1)[1])[0]
        view=targets[0]['claim']
        assert ('text' not in view and 'conditions' not in view) is redraft
        assert ('Source-grounded factual redraft' in prompt) is redraft
        assert (c['text'] not in prompt) is redraft
        assert e['quote'] in prompt
        if redraft:assert 'Explain the output roles' in prompt and c['conditions']['scope'] not in prompt
        return {'content':json.dumps([{'claimId':'c','kind':'reported','text':'网络预测平移和旋转。',
            'conditions':{},'evidenceRefs':['E1'],'detailLevel':'fulltext'}])}
    revised=repair_rejected({'claims':[c]},check,[e],'解释网络预测的变化',invoke,json.loads,
        fact_redraft=redraft,requirement_context=requirements,checkpoint=lambda v:saved.append(deepcopy(v)))
    pending=next(v['pending']['request']['prepared'] for v in saved if v.get('pending'))
    assert pending['originals']['c']['text']==c['text']
    assert pending['originals']['c']['conditions']==c['conditions']
    assert [c,e,check]==before and revised[0]['evidenceRefs']==c['evidenceRefs']
    assert not verify_claims(revised,[e])['accepted']
    semantic=Mock(return_value=[{'claimId':'c','status':'passed'}])
    assert verify_claims(revised,[e],semantic)['accepted'];semantic.assert_called_once()


def test_unknown_redraft_keeps_exact_pending_request_and_cannot_be_resent_or_retargeted(tmp_path):
    from llm.provider import LLMProviderError
    c,e,check,requirements=inputs();saved=[]
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run({'runId':'r','taskId':'t'});repo.begin_execution('r')
    provider=Mock();provider.invoke.side_effect=LLMProviderError('unknown',provider='fixture',model='fixture')
    invoker=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    invoke=lambda prompt:invoker('r','repair_claims',prompt,{'max_tokens':1000})
    kwargs={'fact_redraft':True,'requirement_context':requirements,'checkpoint':lambda v:saved.append(deepcopy(v))}
    with pytest.raises(LLMProviderError):repair_rejected({'claims':[c]},check,[e],'解释',invoke,json.loads,**kwargs)
    pending=deepcopy(saved[-1]);assert pending.get('pending')
    with pytest.raises(UnknownCallError):repair_rejected({'claims':[c]},check,[e],'解释',invoke,json.loads,batch_state=pending,**kwargs)
    assert provider.invoke.call_count==1 and pending==saved[-1]
    changed=[{**requirements[0],'question':'A different target'}]
    with pytest.raises(DeepResearchError,match='保存的修订计划'):
        repair_rejected({'claims':[c]},check,[e],'解释',invoke,json.loads,batch_state=pending,
            fact_redraft=True,requirement_context=changed)
    assert provider.invoke.call_count==1


def test_prospective_designs_keep_their_full_original_configuration_view():
    c,e,check,requirements=inputs();c['kind']='proposal'
    def invoke(prompt):
        assert 'Source-grounded factual redraft' not in prompt
        assert c['text'] in prompt and c['conditions']['scope'] in prompt
        return {'content':'[]'}
    assert repair_rejected({'claims':[c]},check,[e],'设计',invoke,json.loads,
        fact_redraft=True,requirement_context=requirements)==[]


@pytest.mark.parametrize('marker',[None,True,1])
def test_actual_graph_supplies_frozen_requested_requirements_only_for_marked_redrafts(marker,monkeypatch):
    c,e,check,requirements=inputs()
    record={'factRedraftContractVersion':marker,'state':{'reportBody':{'claims':[c]},'evidence':[e],
        'plan':[{'itemId':'i','obligations':requirements}]}}
    def update(rid,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'not_requested','gaps':[]})
    seen=[]
    def invoke(rid,node,prompt,options):
        assert node=='repair_claims'
        enabled=type(marker) is int and marker==1
        assert ('Source-grounded factual redraft' in prompt) is enabled
        if enabled:assert 'Explain the output roles' in prompt and c['text'] not in prompt
        seen.append(prompt);return {'content':'[]'}
    verify=Mock(return_value=check)
    make_verify_node(verify,None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(seen)==1 and record['state']['repairReport']['claims'][0]['text']==c['text']
    assert not record['state']['verifiedReport']['verifiedClaims']


@pytest.mark.parametrize('replacement',[None,True,'1',0,1,2,4])
def test_redraft_mode_is_server_owned_and_frozen(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'factRedraftContractVersion':replacement},start_async=False)
        assert run['factRedraftContractVersion']==3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'factRedraftContractVersion':replacement})
    finally:facade.shutdown()
