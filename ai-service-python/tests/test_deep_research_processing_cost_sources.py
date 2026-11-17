from copy import deepcopy
import hashlib
from unittest.mock import Mock

import pytest

from services.deep_research.processing_cost_sources import include_processing_cost,score

OWNER='owned.pdf';VERSION='a'*16;DIGEST='b'*64
QUERY='additional processing cost storage quality FPS'


def record():
    from test_deep_research_shared_experiment_generation import context
    r,_,_=context();r.update(question='Compare processing cost and rendering FPS.',
        comparisonPlanningContractVersion=2,comparisonReviewBatchContractVersion=2,
        materials=[{'materialId':OWNER,'contentHash':DIGEST}])
    r['state']['outputKind']='paper_comparison'
    return r


def row(i,text,section='Overview',mode='indexed_hybrid',table=None):
    return {'sourceId':f'{OWNER}-v{VERSION}-chunk-{i}','pdfId':OWNER,'text':text,
        'sourceType':'current_paper','retrievalMode':mode,'tableData':table,
        'metadata':{'id':OWNER,'index_version':VERSION,'chunk_index':i,'section_title':section,
                    **({'table_id':section} if section.startswith('Table') else {})},
        'location':{'chunk':i,'section':section}}


def fixture():
    base=[row(0,'Our representation.'),row(1,'Main table header.','Table 1'),
          row(2,'Main result.','Table 1','indexed_requested_row',{'visible':True}),
          row(3,'Another named row.','Table 7','indexed_requested_row',{'visible':True}),
          row(4,'An ablation condition.','Table 6','indexed_scope_condition',{'visible':True})]
    detail=row(6,'We optimize our model for 7000 iterations.','Implementation')
    return base,[*base,detail],detail


def test_mixed_query_retains_main_header_named_rows_and_adds_owned_processing_work():
    base,pool,detail=fixture();before=deepcopy((base,pool));r=record()
    out=include_processing_cost(base,pool,r,QUERY,OWNER,5)
    assert len(out)==5 and out[0]==base[0]
    assert {b['sourceId'] for b in base[:4]}<={v['sourceId'] for v in out}
    added=next(v for v in out if v['sourceId']==detail['sourceId'])
    assert added=={**detail,'retrievalMode':'indexed_processing_cost'}
    assert (base,pool)==before  # No rewritten quotation, inferred result or mutation.


def test_explicit_condition_query_does_not_displace_a_requested_scope_passage():
    base,pool,_=fixture()
    assert include_processing_cost(base,pool,record(),QUERY+' ablation conditions',OWNER,5)==base


def test_an_already_selected_cost_hint_cannot_be_inserted_twice_when_better_detail_needs_context():
    base,pool,_=fixture()
    hint=row(4,'We train our model for some iterations.','Overview')
    base[-1]=hint
    detail=row(8,'Then we fine-tune our model for 7000 iterations.','Implementation')
    # Missing predecessor prevents adding the better detail; the weaker hint is
    # already present and must not be duplicated as a fallback.
    out=include_processing_cost(base,[*base,detail],record(),QUERY,OWNER,5)
    assert len({v['sourceId'] for v in out})==len(out)


def navigation_fixture():
    from test_deep_research_reading_roles import source
    obligations={'o':{'obligationId':'o','question':'Compare processing cost and rendering FPS.',
        'searchQuery':QUERY,'requiredSources':['a-v1','b-v1'],
        'completionCriteria':[{'criterionId':'metrics','requirement':'Compare rendering FPS.',
                               'responseType':'comparison'}]}}
    sources=[]
    for work in ('a','b'):
        sources.extend([
            source(work,'result-'+work,'Table 1: Quantitative results. FPS 100.1 120.2 140.3 160.4 180.5.','Results'),
            source(work,'background-'+work,'We discuss training for 10000 iterations.','Related Work'),
            source(work,'cost-'+work,'We fine-tune our model for 7000 iterations before rendering.','Implementation')])
    return obligations,sources


def test_cost_reaches_bounded_read_without_losing_result_roles():
    from services.deep_research.reading_priority import select_read_sources
    obligations,sources=navigation_fixture();before=deepcopy(sources)
    selected=select_read_sources(sources,obligations,4,priority_version=10,
        substantive=True,measurement_tables=True,processing_cost=True)
    assert {s['sourceId'] for s in selected}=={'cost-a','cost-b','result-a','result-b'}
    assert sources==before and all(s in sources for s in selected)


def test_default_navigation_keeps_legacy_order_and_unrequested_cost_cannot_add_targets():
    from services.deep_research.reading_priority import select_read_sources
    obligations,sources=navigation_fixture()
    assert select_read_sources(sources,obligations,4,priority_version=10,substantive=True)==select_read_sources(
        sources,obligations,4,priority_version=10,substantive=True,processing_cost=False)
    obligations['o'].update(question='Compare rendering FPS.',searchQuery='rendering FPS')
    assert select_read_sources(sources,obligations,4,priority_version=10,substantive=True,
        processing_cost=True)==select_read_sources(sources,obligations,4,priority_version=10,substantive=True)


def test_new_cost_navigation_requires_current_profile_and_explicit_human_request():
    from services.deep_research.processing_cost_sources import enabled
    r=record();assert enabled(r)
    r['comparisonReviewBatchContractVersion']=1;assert not enabled(r)
    r=record();r['question']='Compare FPS only.';assert not enabled(r)


def test_production_read_and_direct_extraction_preserve_owned_cost_quotes_without_model_calls():
    from services.deep_research.graph import make_read_node
    from services.deep_research.extraction import make_batched_extract_node
    from services.deep_research.verification import make_evidence
    obligations,sources=navigation_fixture();r=record()
    r.update(runId='r',readingPriorityContractVersion=8,adaptiveExtractionContractVersion=3)
    r['state'].update(plan=[{'obligations':list(obligations.values())}],sources=sources,evidence=[])
    def update(rid,fn,**kwargs):
        nonlocal r
        r=fn(r);return deepcopy(r)
    def read(rid,sid):
        source=next(s for s in sources if s['sourceId']==sid)
        return {'pages':[{'text':source['text']}],'accessLevel':'fulltext'}
    invoke=Mock(side_effect=AssertionError('Direct extraction must not call a model'))
    make_read_node(read,lambda *_:True,update)({'run_id':'r','source_ids':[s['sourceId'] for s in sources]})
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    for source in (s for s in sources if s['sourceId'].startswith('cost-')):
        evidence=[e for e in r['state']['evidence'] if e['sourceId']==source['sourceId']]
        assert ''.join(e['quote'] for e in evidence)==source['text']
        assert all(e['sourceWorkId']==source['workId'] and e['sourceVersionId']==source['versionId']
                   and e['verification']=={'literal':'passed','semantic':'unchecked'} for e in evidence)
    invoke.assert_not_called()


@pytest.mark.parametrize('version',[None,0,1,True,'2'])
def test_old_and_malformed_profiles_keep_the_frozen_selection(version):
    base,pool,_=fixture();r=record();r['comparisonReviewBatchContractVersion']=version
    assert include_processing_cost(base,pool,r,QUERY,OWNER,5)==base


@pytest.mark.parametrize('human,query',[
    ('Compare FPS.',QUERY),('Ignore processing costs and compare FPS.',QUERY),
    ('Compare processing cost and FPS.','FPS only'),
    ('Compare processing cost and FPS.','ignore processing cost; FPS only')])
def test_cost_must_be_requested_by_human_and_query(human,query):
    base,pool,_=fixture();r=record();r['question']=human
    assert include_processing_cost(base,pool,r,query,OWNER,5)==base


@pytest.mark.parametrize('defect',['foreign','version','abstract','forged','duplicate','unallowed_owner'])
def test_ambiguous_or_unowned_source_cannot_be_promoted(defect):
    base,pool,detail=fixture();r=record()
    if defect=='foreign':detail['metadata']['id']='another.pdf'
    elif defect=='version':detail['metadata']['index_version']='c'*16
    elif defect=='abstract':detail['accessLevel']='abstract'
    elif defect=='forged':detail['sourceId']='forged'
    elif defect=='duplicate':pool.append(deepcopy(detail))
    else:r['materials']=[]
    assert include_processing_cost(base,pool,r,QUERY,OWNER,5)==base


def test_better_implementation_detail_replaces_a_generic_cost_hint():
    base,pool,detail=fixture()
    base[4]=row(4,'We train for 1000 iterations.','Introduction')
    pool=[*base,detail]
    out=include_processing_cost(base,pool,record(),QUERY,OWNER,5)
    assert detail['sourceId'] in {v['sourceId'] for v in out}


def test_cost_detail_with_pronoun_keeps_exact_predecessor_and_never_invents_context():
    from services.deep_research.source_continuity import needs_preceding_context
    base,pool,_=fixture();base[3]['retrievalMode']='indexed_hybrid'
    prev=row(5,'Our refinement prepares the representation.','Implementation')
    detail=row(6,'It is optimized by our model for 7000 iterations.','Implementation')
    assert needs_preceding_context(detail)
    pool=[*base,prev,detail]
    out=include_processing_cost(base,pool,record(),QUERY,OWNER,5)
    assert [v['sourceId'] for v in out[1:3]]==[prev['sourceId'],detail['sourceId']]
    assert out[1]['contextForSourceId']==detail['sourceId'] and len(out)==5
    assert include_processing_cost(base,[*base,detail],record(),QUERY,OWNER,5)==base


def pdf_row(page,text):
    loc={'page':page,'offset':0}
    source_id='src_'+hashlib.sha256(f'{OWNER}:{DIGEST}:{loc}'.encode()).hexdigest()
    return {'sourceId':source_id,'pdfId':OWNER,'contentHash':DIGEST,'accessLevel':'fulltext',
            'text':text,'location':loc,'retrievalMode':'pdf_lexical_fallback'}


def test_verified_pdf_fallback_can_select_cost_without_network_or_index():
    base=[pdf_row(1,'Our representation.'),pdf_row(2,'Other text.')]
    detail=pdf_row(3,'We fine-tune the representation for 7000 iterations.')
    out=include_processing_cost(base,[*base,detail],record(),QUERY,OWNER,2)
    assert out==[base[0],{**detail,'retrievalMode':'pdf_processing_cost'}]
    broken={**detail,'sourceId':'src_forged'}
    assert include_processing_cost(base,[*base,broken],record(),QUERY,OWNER,2)==base


def test_related_work_quality_numbers_and_method_names_are_not_cost_evidence():
    assert score(row(1,'We optimize for 7000 iterations.','Related Work'))==0
    assert score(row(1,'We report PSNR 30 and FPS 200.','Results'))==0
    assert score(row(1,'Our model has a pruning and distillation module.','Method'))==0


def test_final_source_selection_hook_uses_only_existing_candidates():
    from services.deep_research.local_sources import LocalTaskRetriever
    base,pool,detail=fixture();r=record();r['scopeEvidenceContractVersion']=0
    repo=Mock();repo.require_run.return_value=r;get=Mock();parse=Mock()
    retriever=LocalTaskRetriever(repo,'r',lambda *_:True,origin='http://unused.invalid',get=get,parse=parse)
    out=retriever._scope_evidence(base,pool,QUERY,OWNER,5)
    assert detail['sourceId'] in {v['sourceId'] for v in out}
    get.assert_not_called();parse.assert_not_called()
