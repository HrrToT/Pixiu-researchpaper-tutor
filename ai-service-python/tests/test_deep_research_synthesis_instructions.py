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
    if type(value) is int and value == 2:
        assert enabled(r,'paper_comparison')
        assert template(r)!=template({k:v for k,v in r.items() if k!='synthesisInputContractVersion'})
    else:
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
        assert r['synthesisInputContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'synthesisInputContractVersion':client_value if client_value!=2 else 1})
    finally:facade.shutdown()


def test_comparison_v2_retains_complete_data_body_grammar_and_recovers_evidence_capacity():
    from services.deep_research.factual_prompt import build
    from services.deep_research.shared_strings import unpack
    from services.deep_research.nested_tables import unpack as untables
    requirements=[{'obligationId':'mechanism','question':'比较机制与有条件的选择',
        'requiredSourceAliases':['P1','P2'],'completionCriteria':[{'criterionId':'actual',
            'requirement':'Keep each original method, source conditions and numeric table values.'}]}]
    sources={'P1':{'workId':'a-v1','title':'A'},'P2':{'workId':'b-v1','title':'B'}}
    q='只依据两篇论文；不从压缩倍数推断速度。'
    params=(q,'paper_comparison',500,5,['结论','共同维度'],requirements,sources,
            'EXACT_EVIDENCE','EXACT_TABLES','claimId,text,kind,conditions,evidenceRefs,obligationIds','metric')
    old_record={**record(),'premiseDraftContractVersion':2}
    old=build(old_record,*params,drafting_schema=True)
    new=build({**old_record,'synthesisInputContractVersion':2},*params,drafting_schema=True)
    packet=json.JSONDecoder().raw_decode(new.split('Frozen requested criteria and source requirements (questions, never facts):\n',1)[1])[0]
    assert (untables(unpack(packet)) if isinstance(packet,dict) and 'strings' in packet else packet)==requirements
    registry=json.JSONDecoder().raw_decode(new.split('Source registry (P keys identify papers, never evidenceRefs): ',1)[1])[0]
    assert registry==sources and 'Question: '+q+'\n' in new
    assert 'maximum claims: 5' in new and 'character limit: 500' in new
    assert 'EXACT_EVIDENCE' in new and 'EXACT_TABLES' in new
    field_line=lambda p:next(line for line in p.splitlines() if line.startswith('Each claim has exactly:'))
    assert field_line(old)==field_line(new)
    assert len(new.encode()) < len(old.encode())-3000


@pytest.mark.parametrize('kind',['claim_verification','experiment_design'])
def test_v2_does_not_replace_other_research_paths(kind):
    assert template({**record(),'synthesisInputContractVersion':2},kind)==template(record(),kind)


def test_v2_still_compiles_through_existing_factual_and_numeric_checks():
    from services.deep_research.authored_body import decode
    from services.deep_research.verification import precheck_claims
    raw={'claimId':'c','kind':'reported','evidenceRefs':['e'],
         'body':{'prose':{'text':'The result is 31.25 dB.','conditions':{}}},'detailLevel':'fulltext'}
    claim=decode(raw)
    evidence=[{'evidenceId':'e','quote':'The result is 31.25 dB.','sourceContext':'The result is 31.25 dB.',
               'sourceWorkId':'a','sourceVersionId':'v1','accessLevel':'fulltext','location':{},
               'verification':{'literal':'passed','semantic':'unchecked'}}]
    assert precheck_claims([claim],evidence)['candidates']
    claim['text']='The result is 99.0 dB.'
    assert precheck_claims([claim],evidence)['rejected'][0]['reason']=='numeric_mismatch'
