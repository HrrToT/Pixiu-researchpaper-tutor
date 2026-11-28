"""Dependency order, bounded frontiers and durable transition replay."""
from copy import deepcopy
import json
import re
import sqlite3

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.coverage import validate_plan, coverage_gaps
from services.deep_research.dependencies import initialize, journal, scoped_record, scoped_updater, finish_assessment, advance_frontier
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence
from test_deep_research_clarification_context import wait_worker
from test_deep_research_plan_resume import Model


def plan(extra=False):
    def item(key, dependencies=()):
        return {'itemId': key, 'question': 'Research ' + key, 'dependencies': list(dependencies),
                'obligations': [{'obligationId': 'o-' + key, 'question': 'Research ' + key,
                    'requiredSources': ['p'], 'completionCriteria': [{'criterionId': 'c-' + key,
                        'requirement': 'Explain mechanism ' + key, 'responseType': 'explanation'}]}]}
    return [item('C', ['A', 'B']), item('A'), item('B'), *([item('D')] if extra else [])]


def begin(tmp_path, extra=False, start=True, extra_contracts=None):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    values=plan(extra)
    repo.create_run({'runId':'r','taskId':'t','question':'Explain the three mechanisms.',
        'materials':[{'materialId':'p','pdfId':'p','versionId':'v1'}], 'dependencyContractVersion':1,
        'adaptiveResearchContractVersion':1,'planCompletionContractVersion':1,**(extra_contracts or {}),
        'state':{'plan':values,'planRevision':0,'dependencyExecution':initialize(values)}})
    if start:
        repo.begin_execution('r')
    return repo


def test_frontier_scoping_preserves_full_plan_and_earlier_gaps(tmp_path):
    repo=begin(tmp_path)
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'gaps':[{'obligationId':'o-C','question':'C','checked':False}]}})
    update=scoped_updater(repo.update_run)
    view=update('r',lambda r:{**r,'state':{**r['state'],
        'plan':[{**i,'status':'completed'} for i in r['state']['plan']], 'gaps':[]}},expected_revision=None)
    assert [i['itemId'] for i in view['state']['plan']]==['A','B']
    full=repo.require_run('r')['state']
    assert [i['itemId'] for i in full['plan']]==['C','A','B']
    assert full['gaps']==[{'obligationId':'o-C','question':'C','checked':False}]


def test_pending_frontier_transition_survives_repository_restart_and_replay(tmp_path):
    repo=begin(tmp_path)
    scoped_updater(repo.update_run)('r',lambda r:{**r,'state':{**r['state'],
        'plan':[{**i,'status':'completed'} for i in r['state']['plan']]}},expected_revision=None)
    output={'gaps':[],'stop_reason':'covered','requery_count':1}
    ready=finish_assessment({'run_id':'r'},output,repo.update_run)
    assert journal(repo.require_run('r'))['active']==['A','B']  # Not ahead of graph checkpoint.
    repo=DeepResearchRepository(repo.db_path); repo.initialize()
    first=advance_frontier({'run_id':'r',**ready},repo.update_run)
    saved=deepcopy(journal(repo.require_run('r')))
    again=advance_frontier({'run_id':'r',**ready},repo.update_run)
    assert first==again and journal(repo.require_run('r'))==saved
    assert saved['active']==['C'] and saved['wave']==1 and first['requery_count']==1
    assert not repo.list_calls('r')


def test_unresolved_prerequisite_blocks_descendant_but_not_other_independent_work(tmp_path):
    repo=begin(tmp_path,extra=True)
    scoped_updater(repo.update_run)('r',lambda r:{**r,'state':{**r['state'],
        'plan':[{**i,'status':'gap' if i['itemId']=='A' else 'completed'} for i in r['state']['plan']],
        'gaps':[{'obligationId':'o-A','question':'A','checked':True}]}},expected_revision=None)
    ready=finish_assessment({'run_id':'r'},{'gaps':[{'obligationId':'o-A'}],
        'stop_reason':'no_new_evidence','requery_count':1},repo.update_run)
    advance_frontier({'run_id':'r',**ready},repo.update_run)
    assert journal(repo.require_run('r'))['active']==['D']
    scoped_updater(repo.update_run)('r',lambda r:{**r,'state':{**r['state'],
        'plan':[{**i,'status':'completed'} for i in r['state']['plan']], 'gaps':[]}},expected_revision=None)
    final=finish_assessment({'run_id':'r'},{'gaps':[],'stop_reason':'covered','requery_count':1},repo.update_run)
    assert not final['dependency_transition']
    assert {g['obligationId'] for g in final['gaps']}=={'o-A','o-C'}
    assert next(g for g in final['gaps'] if g['obligationId']=='o-C')['checked'] is False
    assert 'C' not in journal(repo.require_run('r'))['settled']


def test_budget_stop_does_not_advance_ready_work(tmp_path):
    repo=begin(tmp_path)
    scoped_updater(repo.update_run)('r',lambda r:{**r,'state':{**r['state'],
        'plan':[{**i,'status':'completed'} for i in r['state']['plan']]}},expected_revision=None)
    result=finish_assessment({'run_id':'r','budget_exhausted':True},
        {'gaps':[],'stop_reason':'budget_exhausted','requery_count':0},repo.update_run)
    assert not result['dependency_transition']
    assert result['gaps'][0]['obligationId']=='o-C' and result['gaps'][0]['checked'] is False


@pytest.mark.parametrize('bad', [{'active':['C','A','B']},{'active':['foreign']},{'wave':True},
    {'settled':['A'],'satisfied':['B']},{'pending':{'id':'forged','active':['C'],'fromWave':0}}])
def test_invalid_journal_rejects_before_work(tmp_path,bad):
    repo=begin(tmp_path)
    record=repo.require_run('r')
    record['state']['dependencyExecution'].update(bad)
    with pytest.raises(DeepResearchError,match='依赖'):
        scoped_record(record)


@pytest.mark.parametrize('restart', [False,True])
def test_compiled_graph_never_investigates_descendant_before_saved_prerequisites(tmp_path,restart):
    repo=begin(tmp_path)
    events=[]
    paragraph=lambda key: f'The {key} mechanism uses supervised image reconstruction with fixed camera inputs and a declared training loss.'
    def invoke(_,node,prompt,*args,**kwargs):
        active=journal(repo.require_run('r'))['active'] if repo.require_run('r')['state'].get('dependencyExecution') else []
        events.append((node,tuple(active)))
        if node=='resolve_brief': value={'outputKind':'claim_verification','clarification':''}
        elif node=='plan': value=plan()
        elif node=='extract':
            text=re.search(r'Text \(page .*?\): (.*?)\n\nObligations',prompt,re.S).group(1)
            obligations=json.loads(prompt.split('Obligations (with IDs): ',1)[1].split('\n',1)[0])
            matches=[o['obligationId'] for o in obligations if o['obligationId'][-1]+' mechanism' in text]
            value=[{'quote':text,'obligationIds':matches,'conditions':{}}] if matches else []
            if active==['A','B']: assert 'Research C' not in prompt
        elif node=='assess_relevance':
            rows=json.loads(prompt.split('Pairs:\n',1)[1].split('\n\nReturn',1)[0])
            value=[{'pairId':r['pairId'],'relevant':r['obligationId'][-1]+' mechanism' in r['quote']} for r in rows]
        elif node=='synthesize': raise DeepResearchError('fixture_stop','Inspect routing only, not content quality.')
        else: raise AssertionError(node)
        return {'content':json.dumps(value),'finishReason':'stop'}
    def retrieve(query,pdf_id,limit=5):
        key=re.search(r'Research ([ABC])',query).group(1)
        events.append(('retrieve',key))
        if key=='C': assert set(journal(repo.require_run('r'))['satisfied'])=={'A','B'}
        return [{'sourceId':'s-'+key,'sourceWorkId':'p','versionId':'v1','text':paragraph(key),
                 'location':{'page':1},'accessLevel':'fulltext'}]
    def build(conn):
        return build_deep_research_graph(llm_invoke=invoke,retrieve_fn=retrieve,
            read_fn=lambda rid,sid:{'accessLevel':'fulltext','pages':[{'page':1,'text':paragraph(sid[-1])}]},
            scope_validator=lambda *_:True,make_evidence_fn=make_evidence,coverage_gaps_fn=coverage_gaps,
            verify_claims_fn=lambda *_:{},repo_update=repo.update_run,repo_publish=repo.publish_report,
            validate_plan_fn=validate_plan,checkpoint_conn=conn)
    config={'configurable':{'thread_id':'r'}}
    path=str(repo.db_path)+'.checkpoints'
    with sqlite3.connect(path,check_same_thread=False) as conn:
        graph=build(conn)
        if restart:
            graph.invoke({'run_id':'r','execution_epoch':1},config=config,interrupt_after=['advance_frontier'])
            assert graph.get_state(config).next==('acquire',)
            assert journal(repo.require_run('r'))['active']==['C']
        else:
            with pytest.raises(DeepResearchError,match='routing'):
                graph.invoke({'run_id':'r','execution_epoch':1},config=config)
    if restart:
        with sqlite3.connect(path,check_same_thread=False) as conn:
            with pytest.raises(DeepResearchError,match='routing'):
                build(conn).invoke(None,config=config)
    retrieved=[value for node,value in events if node=='retrieve']
    assert set(retrieved[:2])=={'A','B'} and retrieved[2:]==['C']
    assert journal(repo.require_run('r'))['satisfied']==['A','B','C']
    assert not repo.require_run('r').get('publication',{}).get('published')


@pytest.mark.parametrize('replacement',[0,True,'1',None])
def test_dependency_contract_is_server_owned(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'研究方法',
            'deferStart':True,'dependencyContractVersion':replacement},start_async=False)
        assert run['dependencyContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'dependencyContractVersion':replacement})
    finally: facade.shutdown()


def test_human_edit_removes_a_scheduled_descendant_before_resume(tmp_path):
    repo=begin(tmp_path,extra_contracts={'planEditContractVersion':1,'planResumeContractVersion':1})
    values=plan()
    state=repo.require_run('r')['state']
    state['plan']=[{**i,'status':'completed' if i['itemId'] in {'A','B'} else 'pending'} for i in values]
    repo.update_run('r',lambda r:{**r,'state':state})
    ready=finish_assessment({'run_id':'r'},{'gaps':[],'stop_reason':'covered'},repo.update_run)
    config={'configurable':{'thread_id':'r'}}
    conn=sqlite3.connect(str(repo.db_path)+'.checkpoints',check_same_thread=False)
    try:
        graph=build_deep_research_graph(llm_invoke=lambda *_:pytest.fail('No setup generation'),
            retrieve_fn=lambda *_:[],read_fn=lambda *_:{},scope_validator=lambda *_:True,
            make_evidence_fn=make_evidence,coverage_gaps_fn=coverage_gaps,verify_claims_fn=lambda *_:{},
            repo_update=repo.update_run,repo_publish=repo.publish_report,validate_plan_fn=validate_plan,checkpoint_conn=conn)
        graph.update_state(config,{'run_id':'r','execution_epoch':1,'plan_revision':0,**ready},as_node='assess')
        assert graph.get_state(config).next==('advance_frontier',)
    finally: conn.close()
    paused=repo.transition('r','paused')
    queries=[]
    def retrieve(query,pdf_id,limit=5):
        queries.append(query)
        return []
    facade=ResearchFacade(repo,build_deep_research_graph,llm_client=Model(False),
                          retriever=retrieve,scope_validator=lambda *_:True)
    try:
        edited=facade.action('r','plan',{'requestId':'edit','expectedRunRevision':paused['runRevision'],
            'planRevision':0,'plan':[plan(extra=True)[-1]]})
        current=repo.require_run('r')
        assert journal(current)['active']==['D']
        retired=current['state']['planEditHistory'][0]['retiredOutputs']['dependencyExecution']
        assert retired['pending']['active']==['C']
        facade.action('r','resume',{'requestId':'resume','expectedRunRevision':edited['runRevision']})
        result=wait_worker(facade,repo,'r','failed')
        assert result['errorCode']=='fixture_stop'
        assert queries and all('Research D' in q and 'Research C' not in q for q in queries)
        assert [i['itemId'] for i in result['state']['plan']]==['D']
    finally: facade.shutdown()
