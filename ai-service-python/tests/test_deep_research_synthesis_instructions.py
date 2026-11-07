from copy import deepcopy
import json

import pytest

from services.deep_research.synthesis_instructions import enabled
from test_deep_research_factual_prompt import template


def record():
    return {'synthesisInputContractVersion':1,'factualPromptContractVersion':3,
            'authoredBodyContractVersion':1,'scopeExpressionContractVersion':5}


@pytest.mark.parametrize('value',[None,True,False,0,2,'1'])
def test_consolidation_requires_strict_server_policy_and_modern_factual_format(value):
    r={**record(),'synthesisInputContractVersion':value}
    assert not enabled(r,'paper_comparison')
    assert template(r)==template({k:v for k,v in r.items() if k!='synthesisInputContractVersion'})


def test_experiments_and_unversioned_body_keep_the_original_prompt():
    r=record();assert not enabled(r,'experiment_design')
    assert template(r,'experiment_design')==template({**r,'synthesisInputContractVersion':0},'experiment_design')
    r.pop('authoredBodyContractVersion');assert not enabled(r,'claim_verification')
    assert template(r)==template({**r,'synthesisInputContractVersion':0})


@pytest.mark.parametrize('version',[1,2])
def test_older_factual_drafting_contracts_do_not_receive_the_v3_only_table_rules(version):
    r={**record(),'factualPromptContractVersion':version}
    assert not enabled(r,'paper_comparison')
    assert template(r)==template({**r,'synthesisInputContractVersion':0})


def test_new_template_keeps_literal_question_source_registry_and_complete_criteria():
    from services.deep_research.factual_prompt import build
    from services.deep_research.shared_strings import unpack
    from services.deep_research.nested_tables import unpack as untables
    q='比较原话：Question: 不得改写；{"$":3}。限500字。'
    obligations=[{'obligationId':str(i),'question':'相同完整问题'*8,
        'requiredSourceAliases':['P1','P2'],'completionCriteria':[{'criterionId':'a',
        'requirement':'相同完整要求'*10,'responseType':'explanation','literal':{'$':7,'@':'literal'}}]}
        for i in range(4)]
    sources={'P1':{'workId':'a-v1','title':'A'},'P2':{'workId':'b-v2','title':'B'}}
    before=deepcopy(obligations)
    prompt=build(record(),q,'paper_comparison',500,5,['结论'],obligations,sources,
        'EVIDENCE','TABLES','claimId,text,kind,conditions,evidenceRefs,obligationIds','metric',drafting_schema=True)
    packet=json.JSONDecoder().raw_decode(prompt.split('Frozen requested criteria and source requirements (questions, never facts):\n',1)[1])[0]
    decoded=untables(unpack(packet)) if isinstance(packet,dict) and set(packet)=={'strings','value'} else packet
    registry=json.JSONDecoder().raw_decode(prompt.split('Source registry (P keys identify papers, never evidenceRefs): ',1)[1])[0]
    assert decoded==before==obligations and registry==sources and 'Question: '+q+'\n' in prompt
    assert 'body' in prompt
    for phrase in ('controlled speedup','paper/pool absence'):
        assert phrase in prompt
    assert 'whole-sequence offline fitting' in prompt and 'all-scene aggregates' in prompt
    assert 'without own support' in prompt and 'Every raw number' in prompt


def test_actual_graph_preserves_inputs_and_appends_scope_objective_and_process_rules_once():
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.evidence_wire import decode
    _,_,base=node_capture(3);base.update(record())
    saved={'r':base};sent=[]
    class Stop(Exception):pass
    def update(rid,fn,**kwargs):saved['r']=fn(deepcopy(saved['r']));return deepcopy(saved['r'])
    def stop(rid,node,prompt,options,**kwargs):sent.append(prompt);raise Stop()
    with pytest.raises(Stop):make_synthesize_node(stop,update)({'run_id':'r'})
    assert len(sent)==1 and sent[0].count('Other points use body.prose')==1
    packet=json.JSONDecoder().raw_decode(sent[0].split('Evidence summaries:\n',1)[1])[0]
    assert decode(packet) and saved['r']['state']['evidence']==base['state']['evidence']
    assert saved['r']['state']['synthesisPremiseAllocation']['factualInputContractVersion']==1
    assert 'Keep objective, intended effect' not in sent[0]  # disabled fixture policy stays disabled
    assert 'source reports' in sent[0] and 'Keep routing IDs out of prose' not in sent[0]


@pytest.mark.parametrize('client_value',[None,True,0,2])
def test_server_owns_policy_and_cannot_mutate_an_existing_run(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较论文','deferStart':True,
            'synthesisInputContractVersion':client_value},start_async=False)
        assert r['synthesisInputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'synthesisInputContractVersion':client_value})
    finally:facade.shutdown()
