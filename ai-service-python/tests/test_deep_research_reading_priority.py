from copy import deepcopy
import pytest
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.graph import make_read_node
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository


def source(paper,chunk,section,text,obligations=('input','training','fps')):
    return {'sourceId':paper+'-v'+'a'*16+'-chunk-'+str(chunk),'workId':paper,'ownerMaterialId':paper,
        'versionId':'v1','contentHash':str(chunk),'accessLevel':'fulltext','text':text,
        'obligationIds':list(obligations),'location':{'chunk':chunk,'section':section}}


def inputs():
    obs={key:{'obligationId':key,'question':query,'requiredSources':['a','b']} for key,query in (
        ('input','What input data?'),('training','online or offline training?'),('fps','FPS comparison conditions'))}
    sources=[]
    for paper in ('a','b'):
        sources.extend(source(paper,i,'Introduction','Our model is a useful approach.') for i in range(5))
        sources.extend([
            source(paper,20,'Method','The input to our method is monocular images with calibrated camera poses.'),
            source(paper,30,'Implementation','We initially train the model. Subsequently we jointly train both components for fixed iterations.'),
            source(paper,40,'Results','We measure rendering at 30 FPS on an NVIDIA RTX GPU at resolution 800x800.')])
    return obs,sources


def test_reading_covers_each_papers_actual_requested_operations_with_unchanged_cap():
    obs,sources=inputs();before=deepcopy(sources)
    selected=select_read_sources(sources,obs,6)
    assert len(selected)==6 and {s['sourceId'] for s in selected}=={
        source(p,c,'','')['sourceId'] for p in ('a','b') for c in (20,30,40)}
    assert sources==before and all(s in sources for s in selected)


@pytest.mark.parametrize('foreign',[False,True])
def test_an_exact_predecessor_keeps_its_identity_and_cannot_cross_work_scope(foreign):
    obs={'o':{'obligationId':'o','question':'smoothing mechanism','requiredSources':['a']}}
    prior=source('a',26,'Technique','We add Gaussian noise to time inputs and decay it over iterations.',('o',))
    main=source('a',27,'Technique','This defines the time perturbation and its noise schedule. Equation: x = t + noise.',('o',))
    if foreign:prior['workId']='b'
    selected=select_read_sources([main,prior],obs,2)
    if not foreign:
        assert selected==[prior,main]
    else:
        assert prior not in selected


def test_new_graph_read_order_is_gated_and_existing_sources_are_not_overwritten():
    obs,sources=inputs()
    def run(version):
        record={'readingPriorityContractVersion':version,'state':{'sources':sources,
            'plan':[{'obligations':list(obs.values())}]},'budget':{'profile':'standard'}}
        seen=[]
        def update(_rid,change,**_):
            nonlocal record
            record=change(deepcopy(record));return deepcopy(record)
        def read(_rid,sid):
            seen.append(sid);return {'accessLevel':'fulltext','pages':[{'page':1,'text':'Read original passage.'}]}
        make_read_node(read,lambda *_:True,update)({'run_id':'r','source_ids':[s['sourceId'] for s in sources]})
        assert record['state']['sources']==sources and len(seen)==12
        return seen
    old=run(0);new=run(1)
    for paper in ('a','b'):
        assert source(paper,40,'','')['sourceId'] in new
    assert old!=new


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_reading_policy_is_server_owned_and_immutable_even_for_bool_one(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'比较论文',
            'readingPriorityContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['readingPriorityContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'readingPriorityContractVersion':replacement})
    finally:facade.shutdown()
