import json
from unittest.mock import Mock

from llm.client import DeepSeekLLM
from services.deep_research.repair import repair_rejected
from services.deep_research.structured_output import messages
from services.deep_research.verification import verify_claims
from test_deep_research_quantity_words import setup
from test_deep_research_structured_output import repository, tracked


def test_higher_priority_revision_policy_does_not_freeze_rejected_conditions():
    legacy=messages('repair_claims','probe',5)[0]['content']
    new=messages('repair_claims','probe',6)[0]['content']
    assert 'requested relationships and conditions' in legacy
    assert 'in text AND conditions' not in legacy
    assert 'in text AND conditions' in new
    assert 'keep only necessary supported scope' in new
    assert 'requested relationships and conditions' not in new
    assert 'BOTH entities' in new and len(new.encode('utf8'))+128<=1024
    for node in ('synthesize','synthesize_compact','synthesize_audience','plan','extract','verify'):
        assert messages(node,'probe',5)==messages(node,'probe',6)


def test_actual_native_revision_removes_rejected_condition_and_requires_own_citation_recheck(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=6)
    c,ev=setup('网络预测平移和旋转。')
    c['conditions']={'context':'后四维是旋转。'}
    rejected=verify_claims([c],[ev],quantity_spelling_version=2)
    assert rejected['rejected'][0]['missingReportedNumbers']==['4e0']
    raw=json.dumps({'items':[{'claimId':'c','kind':'reported','text':c['text'],
        'conditions':{},'evidenceRefs':['E1'],'detailLevel':'fulltext'}]},ensure_ascii=False)
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'message':{'content':raw},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}}
    sends=[]
    def post(url,**kwargs):
        sends.append(kwargs['json']);system=kwargs['json']['messages'][0]['content']
        assert 'in text AND conditions' in system and 'keep only necessary supported scope' in system
        assert '4e0' in kwargs['json']['messages'][-1]['content']
        return response
    monkeypatch.setattr('llm.client.requests.post',post)
    invoker=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid',timeout_seconds=2))
    revised=repair_rejected({'claims':[c]},rejected,[ev],'解释预测的变化',
        lambda prompt:invoker('r','repair_claims',prompt,{'max_tokens':1000}),json.loads)
    assert len(sends)==1 and revised[0]['conditions']=={} and c['conditions']=={'context':'后四维是旋转。'}
    checker=Mock(return_value=[{'claimId':'c','status':'passed'}])
    assert verify_claims(revised,[ev],checker,quantity_spelling_version=2)['accepted']
    checker.assert_called_once()
    assert not verify_claims(revised,[ev],quantity_spelling_version=2)['accepted']
