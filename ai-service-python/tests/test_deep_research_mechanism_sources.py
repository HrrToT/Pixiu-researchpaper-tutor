from copy import deepcopy
import pytest
from services.deep_research.mechanism_sources import qualitative,for_query,prefer_sources,overview_score,enabled


def record(question='解释减少存储的机制，不要比较性能数值。',version=1):
    return {'mechanismEvidenceContractVersion':version,'question':question,'state':{'outputKind':'paper_comparison','plan':[
        {'obligations':[{'obligationId':'o','question':question,'searchQuery':'storage compression mechanism',
            'requiredSources':['p'],'completionCriteria':[{'requirement':'解释机制','responseType':'explanation'}]}]}]}}


def row(i,section,text,owner='p',version='a'*16):
    return {'sourceId':f'{owner}-v{version}-chunk-{i}','pdfId':owner,'accessLevel':'fulltext','text':text,
        'metadata':{'id':owner,'index_version':version,'chunk_index':i,'section_title':section}}


@pytest.mark.parametrize('q',['解释减少存储的机制，不要比较性能数值。','Explain the compression mechanism; do not report numbers.',
    '请解释原理，无需列出FPS。','它们分别在哪些环节减少冗余？400字以内。'])
def test_unambiguous_human_mechanism_intent(q):assert qualitative(q)


@pytest.mark.parametrize('q',['解释机制，并给出具体数值。','不要只讲机制，给我FPS数值。','不用公式但要列出速度数值。',
    'Explain the mechanism but report memory values.','比较FPS、PSNR和存储大小。'])
def test_explicit_numeric_requests_keep_measurement_routing(q):assert not qualitative(q)


def test_only_new_matching_source_bound_plan_can_enable_routing():
    for version in (None,True,0,5,'1'):assert not for_query(record(version=version),'storage compression mechanism','p')
    assert for_query(record(),'storage compression mechanism','p')
    assert not for_query(record(),'unrelated query','p')
    assert not for_query(record(),'storage compression mechanism','foreign')
    r=record();r['state']['outputKind']='experiment_design';assert not enabled(r)


def test_method_slots_do_not_change_text_identity_or_expand_limit():
    seed=[row(1,'Results','benchmark storage size'),row(2,'Table 1','Table caption: size results'),row(3,'References','cited paper')]
    core=row(4,'PROPOSED METHOD','Our method uses a pipeline to reduce redundant attributes.')
    more=row(5,'Methods','Our approach encodes attributes using a context model.')
    candidates=[*seed,core,more];before=deepcopy(candidates)
    out=prefer_sources(seed,candidates,record(),'storage compression mechanism','p',3)
    assert out==[core,more,seed[0]] and candidates==before and len(out)==3
    assert prefer_sources(seed,candidates,record(version=0),'storage compression mechanism','p',3)==seed
    assert prefer_sources(seed,candidates,record(),'storage compression mechanism','p',1)==seed[:1]


@pytest.mark.parametrize('change',['foreign','version','id','duplicate'])
def test_foreign_stale_or_ambiguous_candidates_never_enter_reserved_slots(change):
    seed=[row(1,'Results','storage'),row(2,'Table 1','Table caption: sizes')]
    core=row(4,'Methods','Our pipeline reduces redundancy.')
    if change=='foreign':core=row(4,'Methods','Our pipeline reduces redundancy.',owner='foreign')
    if change=='version':core=row(4,'Methods','Our pipeline reduces redundancy.',version='b'*16)
    if change=='id':core['sourceId']='forged-id'
    pool=[*seed,core,deepcopy(core)] if change=='duplicate' else [*seed,core]
    assert prefer_sources(seed,pool,record(),'storage compression mechanism','p',2)==seed


def test_premise_budget_receives_overviews_from_each_paper_before_titles_and_tables():
    from services.deep_research.synthesis_evidence import order_premises,fit_premises
    rows=[]
    for work in ('a','b'):
        for kind,section,quote in [('title','Document opening','Paper title'),('method','PROPOSED METHOD','Our pipeline reduces redundancy by changing the representation.')]:
            rows.append({'evidenceId':work+kind,'sourceWorkId':work,'quote':quote,'location':{'section':section},
                'verification':{'literal':'passed'}})
    plan=[{'obligations':[{'obligationId':w,'question':'说明机制','requiredSources':[w],
        'completionCriteria':[{'criterionId':'c','requirement':'说明机制','responseType':'explanation'}]} for w in ('a','b')]}]
    new,bundles=order_premises(rows,plan,mechanism_overview=True)
    assert [e['evidenceId'] for e in new[:2]]==['amethod','bmethod']
    assert [b['evidenceIds'] for b in bundles]==[['amethod'],['bmethod']]
    assert order_premises(rows,plan)[0][0]['evidenceId']=='atitle'


def test_ranking_is_not_a_semantic_approval_and_table_word_overlap_is_not_a_method():
    assert overview_score('Our pipeline gets good results','References')==0
    assert overview_score('Table caption: pipeline metrics','Methods')==0
    assert overview_score('Our pipeline encodes features.','PROPOSED METHOD')>0


def test_contribution_summary_complements_method_introduction_without_using_result_tables():
    seed=[row(1,'Results','storage comparison'),row(2,'Table 1','Table caption: size')]
    method=row(3,'Methods','Our pipeline encodes the representation.')
    contribution=row(4,'unknown','Our contributions include: • spatial context; • channel context; • masking.')
    out=prefer_sources(seed,[*seed,method,contribution],record(),'storage compression mechanism','p',3)
    assert out[:2]==[method,contribution]
    assert overview_score(contribution['text'],'Results')==0


@pytest.mark.parametrize('replacement',[None,True,0,5,'1'])
def test_mechanism_intent_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释机制','deferStart':True,
            'mechanismEvidenceContractVersion':replacement},start_async=False)
        assert run['mechanismEvidenceContractVersion']==4
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'mechanismEvidenceContractVersion':replacement})
    finally:facade.shutdown()


def mixed_record(version=4):
    r=record('比较压缩机制、存储与画质取舍和渲染速度。',version)
    r['state']['plan'][0]['obligations']=[
        {'obligationId':'method','question':'解释压缩机制','searchQuery':'compression mechanism',
         'requiredSources':['p'],'completionCriteria':[{'requirement':'解释压缩机制','responseType':'explanation'}]},
        {'obligationId':'measurement','question':'列出报告的存储与画质指标及测量条件',
         'searchQuery':'storage quality rendering speed reported results','requiredSources':['p'],
         'completionCriteria':[{'requirement':'列出该论文报告的存储与画质指标及其对应设置','responseType':'identification'},
             {'requirement':'列出该论文报告的渲染速度结果及其测量条件','responseType':'identification'}]}]
    return r


def test_mixed_request_keeps_local_mechanism_priority_without_global_measurement_suppression():
    old=mixed_record(3);new=mixed_record(4);before=deepcopy(new)
    assert enabled(old) and not enabled(new)
    assert for_query(old,'storage quality rendering speed reported results','p')
    assert not for_query(new,'storage quality rendering speed reported results','p')
    assert for_query(new,'compression mechanism','p')
    assert not for_query(new,'compression mechanism','foreign') and new==before


@pytest.mark.parametrize('question',['解释减少存储的机制，不要比较性能数值。',
    'Explain the compression mechanism; do not report numbers.','请解释原理，无需列出FPS。'])
def test_version_four_retains_pure_qualitative_reading(question):
    r=record(question,4)
    assert enabled(r) and for_query(r,'storage compression mechanism','p')


def test_planner_query_numbers_do_not_override_unrequested_human_measurements():
    r=record(version=4);r['state']['plan'][0]['obligations'][0]['searchQuery']='compression mechanism FPS PSNR'
    assert for_query(r,'compression mechanism FPS PSNR','p')


def test_mechanism_text_cannot_displace_metric_tables_for_its_sibling_obligation():
    r=mixed_record();seed=[row(1,'Table 1','Table caption: measured results'),row(2,'Results','Measured speed')]
    core=row(3,'Methods','Our pipeline encodes features.')
    assert prefer_sources(seed,[*seed,core],r,'storage quality rendering speed reported results','p',2)==seed
    assert prefer_sources(seed,[*seed,core],r,'compression mechanism','p',2)[0]==core


@pytest.mark.parametrize('version',[1,2,3])
def test_old_mixed_profiles_keep_their_exact_qualitative_route(version):
    r=mixed_record(version)
    assert enabled(r) and for_query(r,'storage quality rendering speed reported results','p')


def test_comparison_reading_preserves_one_author_method_overview_inside_the_same_limit():
    from services.deep_research.reading_priority import select_read_sources

    role = {'kind': 'per_paper', 'requestExcerpt': '压缩机制'}
    obligation = {'obligationId': 'm', 'question': '说明压缩机制', 'comparisonRole': role, 'requiredSources': ['p']}
    sources = []
    for i, section, text in [(1, 'Results', 'Storage measurements.'), (2, 'Results', 'Reported accuracy.'),
                             (3, 'Evaluation', 'Actual benchmark runs.'),
                             (4, 'Methods', 'Our pipeline encodes attributes and filters redundant primitives.')]:
        sources.append({**row(i, section, text), 'workId': 'p', 'versionId': 'v1', 'ownerMaterialId': 'p',
                        'contentHash': f'chunk-{i}', 'location': {'section': section}, 'obligationIds': ['m']})
    before = deepcopy(sources)
    chosen = select_read_sources(sources, {'m': obligation}, 3, mechanism_overviews=True)
    assert len(chosen) == 3 and chosen[0] == sources[3] and sources == before
    assert sources[3] not in select_read_sources(sources, {'m': obligation}, 3)
    invalid = {**sources[3], 'ownerMaterialId': 'other'}
    chosen = select_read_sources([*sources[:3], invalid], {'m': obligation}, 3, mechanism_overviews=True)
    assert invalid not in chosen
    measurement = {**obligation, 'comparisonRole': {'kind': 'per_paper', 'requestExcerpt': '渲染速度'}}
    assert select_read_sources(sources, {'m': measurement}, 3, mechanism_overviews=True) == select_read_sources(
        sources, {'m': measurement}, 3)


def test_comparison_mechanism_bundle_preserves_author_pipeline_passages():
    from services.deep_research.synthesis_evidence import order_premises

    first = 'Our pipeline:\n• Encode the features.\n'
    second = '• Quantize the attributes.\n• Recover the reconstruction.\n'
    full = first + second + 'In summary, storage is reduced.'
    source = {'sourceId': 's', 'workId': 'p', 'ownerMaterialId': 'p', 'versionId': 'v1',
              'accessLevel': 'fulltext', 'text': full, 'location': {'section': 'Introduction'}}
    rows = [{'evidenceId': eid, 'sourceId': 's', 'sourceWorkId': 'p', 'ownerMaterialId': 'p',
             'sourceVersionId': 'v1', 'quote': quote, 'verification': {'literal': 'passed'},
             'location': {'section': 'Introduction', 'sourcePassageStart': start,
                          'sourcePassageEnd': start + len(quote)}}
            for eid, quote, start in [('first', first, 0), ('second', second, len(first))]]
    obligation = {'obligationId': 'm', 'question': '说明压缩机制', 'requiredSources': ['p'],
                  'comparisonRole': {'kind': 'per_paper', 'requestExcerpt': '压缩机制'},
                  'completionCriteria': [{'criterionId': 'c', 'requirement': '说明压缩机制', 'responseType': 'explanation'}]}
    _, bundles = order_premises(rows, [{'obligations': [obligation]}], read_sources=[source],
                                comparison_operations=True, comparison_mechanisms=True)
    bundle, = bundles
    assert bundle['navigationRole'] == 'comparison_operation'
    assert bundle['evidenceIds'] == ['first', 'second']
