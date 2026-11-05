from copy import deepcopy
import pytest

from services.deep_research.reading_roles import quality, score, premise_bundles
from services.deep_research.reading_priority import select_read_sources
from services.deep_research.graph import make_read_node


def source(work, name, text, section='Method', version=None):
    return {'sourceId':name,'workId':work,'ownerMaterialId':work,'versionId':version or work+'-v1',
        'contentHash':name,'accessLevel':'fulltext','text':text,'title':'Study '+work,
        'location':{'section':section},'obligationIds':['o']}


def fixture():
    obs={'o':{'obligationId':'o','question':'比较表示、提取步骤、Dataset-R2的结果和硬件条件',
        'requiredSources':['a-v1','b-v1'],'completionCriteria':[
            {'criterionId':'method','requirement':'表示与提取流程','responseType':'explanation'},
            {'criterionId':'results','requirement':'Dataset-R2的精度数值','responseType':'comparison'},
            {'criterionId':'settings','requirement':'硬件与分辨率条件','responseType':'limitation'}]}}
    rows=[]
    for w in ('a','b'):
        rows += [source(w,'000-'+w,'Index features in an impressive representation method bibliography.','References'),
                 source(w,'001-'+w,'ref','References'),
                 source(w,'method-'+w,'We represent objects with a learned basis. We then transform and construct the final artifact.'),
                 source(w,'result-'+w,'Table 2: Quantitative results on Dataset-R2. Mean accuracy 0.81 0.82 0.83 0.84 0.85 0.86.' ,'Results'),
                 source(w,'setting-'+w,'All experiments use the documented GPU and image resolution. We render at resolution 800x600.','Implementation')]
    return obs,rows


def test_same_cap_covers_both_papers_roles_instead_of_hash_order_or_reference_fragments():
    obs,rows=fixture();before=deepcopy(rows)
    selected=select_read_sources(rows,obs,6,priority_version=10,substantive=True)
    assert {s['sourceId'] for s in selected}=={p+'-'+w for p in ('method','result','setting') for w in ('a','b')}
    assert len(selected)==6 and rows==before
    assert all(s in rows for s in selected)


def test_novelty_does_not_promote_unread_references_over_known_requested_body():
    obs,rows=fixture();body=[s for s in rows if s['sourceId'].startswith(('method','result','setting'))]
    selected=select_read_sources(rows,obs,6,priority_version=10,substantive=True,
        extracted=[(s['sourceId'],s['contentHash']) for s in body])
    assert {s['sourceId'] for s in selected}=={s['sourceId'] for s in body}


def test_literal_bibliography_requests_and_short_equations_are_not_silently_excluded():
    obs={'o':{'obligationId':'o','question':'列出参考文献','requiredSources':['a']}}
    refs=source('a','ref','A. Researcher. An Example Paper. 2025.','References')
    assert select_read_sources([refs],obs,1,substantive=True)==[refs]
    assert quality(refs,'列出参考文献')==(True,True)
    assert quality(source('a','equation','T=3.'))==(True,True)


@pytest.mark.parametrize('wrong', ['version','owner_namespace'])
def test_wrong_version_and_index_namespace_never_gain_read_permission(wrong):
    obs,rows=fixture();forged=source('a','forged','We represent and then construct every requested artifact.')
    if wrong=='version':forged['versionId']='a-v2'
    else:forged['sourceId']='b-v'+'a'*16+'-chunk-3'
    assert forged not in select_read_sources([forged,*rows],obs,12,substantive=True)


def test_result_caption_domain_beats_nearby_table_that_only_mentions_domain_later():
    request={'role':'result','terms':('dataset-r2',)}
    right={'text':'Table I: Quantitative results on Dataset R2. Mean 0.81 0.82 0.83 0.84 0.85 0.86.'}
    wrong={'text':'Table III: Quantitative results on Dataset Z. Mean 0.91 0.92 0.93 0.94 0.95 0.96. Later we discuss Dataset-R2.'}
    assert score(right,request)>score(wrong,request)


def test_graph_policy_is_opt_in_preserves_sources_and_rechecks_scope_before_read():
    obs,rows=fixture();seen=[]
    record={'readingPriorityContractVersion':6,'state':{'outputKind':'paper_comparison','sources':rows,'plan':[{'obligations':list(obs.values())}]},'budget':{}}
    def update(rid,fn,**kwargs):
        nonlocal record
        record=fn(record);return deepcopy(record)
    def read(rid,sid):
        seen.append(sid);s=next(s for s in rows if s['sourceId']==sid)
        return {'pages':[{'text':s['text']}],'accessLevel':'fulltext'}
    make_read_node(read,lambda rid,work:work=='a',update)({'run_id':'r','source_ids':[s['sourceId'] for s in rows]})
    assert seen and all(next(s for s in rows if s['sourceId']==sid)['workId']=='a' for sid in seen)
    assert record['state']['sources']==rows


def test_premise_ranking_does_not_transfer_literal_status_or_cross_version_support():
    obs,_=fixture();quote='We represent a model and construct its output from the transformed state.'
    def ev(eid,version,literal):
        return {'evidenceId':eid,'sourceWorkId':'a','sourceVersionId':version,'ownerMaterialId':'a',
            'quote':quote,'sourceContext':quote,'verification':{'literal':literal},'location':{'section':'Method'}}
    accepted=ev('ok','a-v1','passed');unchecked=ev('unchecked','a-v1','unchecked');wrong=ev('wrong','a-v2','passed')
    original=deepcopy([accepted,unchecked,wrong]);chosen,bundles=premise_bundles([accepted,unchecked,wrong],obs)
    assert chosen==[accepted] and bundles
    assert all(b['source']=='a-v1' and b['evidenceIds']==['ok'] for b in bundles)
    assert [accepted,unchecked,wrong]==original
    # Navigation cannot turn a semantically unsupported passage into an accepted claim.
    from services.deep_research.verification import verify_claims
    target={'claimId':'c','text':'该模型在所有场景保证正确。','kind':'reported','evidenceRefs':['ok'],'conditions':{}}
    result=verify_claims([target],[accepted],lambda *args:[{'claimId':'c','status':'failed','reason':'No guarantee in the source.'}])
    assert not result['accepted']


def test_explicit_two_revisions_of_one_work_each_receive_a_slot_and_a_premise():
    obs={'o':{'obligationId':'o','question':'比较表示','requiredSources':['a-v1','a-v2'],
              'completionCriteria':[{'criterionId':'c','requirement':'比较表示','responseType':'comparison'}]}}
    text='We represent each object by transforming the parameter matrix into a learned basis.'
    rows=[source('a','v1-row',text,version='a-v1'),source('a','v2-row',text,version='a-v2')]
    assert {s['versionId'] for s in select_read_sources(rows,obs,2,substantive=True)}=={'a-v1','a-v2'}
    evidence=[{'evidenceId':s['sourceId'],'sourceWorkId':s['workId'],'sourceVersionId':s['versionId'],
        'quote':s['text'],'sourceContext':s['text'],'verification':{'literal':'passed'},'location':s['location']} for s in rows]
    chosen,bundles=premise_bundles(evidence,obs)
    assert {e['sourceVersionId'] for e in chosen}=={'a-v1','a-v2'}
    assert {b['source'] for b in bundles}=={'a-v1','a-v2'}


@pytest.mark.parametrize('change', [None,'sourceId','sourceWorkId','sourceVersionId','contentHash','sourceContext','page','offset','section','end','unchecked'])
def test_dangling_later_step_keeps_only_an_exact_owned_contiguous_predecessor(change):
    first='We fuse calibrated depths into an implicit field. '
    second='Subsequently, we extract a mesh from this field.'
    def row(eid,quote,start,end):
        return {'evidenceId':eid,'quote':quote,'sourceId':'owned','sourceWorkId':'a','sourceVersionId':'a-v1',
                'contentHash':'snapshot','sourceContext':first+second,'verification':{'literal':'passed'},
                'location':{'page':3,'offset':200,'section':'Method','sourcePassageStart':start,'sourcePassageEnd':end}}
    prior=row('prior',first,0,len(first));lead=row('lead',second,len(first),len(first+second))
    if change in {'sourceId','sourceWorkId','sourceVersionId','contentHash','sourceContext'}:prior[change]='different'
    elif change in {'page','offset','section'}:prior['location'][change]='different'
    elif change=='end':prior['location']['sourcePassageEnd']-=1
    elif change=='unchecked':prior['verification']['literal']='unchecked'
    obs={'o':{'obligationId':'o','question':'提取流程','requiredSources':['a-v1'],
              'completionCriteria':[{'criterionId':'c','requirement':'提取流程','responseType':'procedure'}]}}
    _,bundles=premise_bundles([prior,lead],obs)
    target=next(b for b in bundles if 'lead' in b['evidenceIds'])
    assert target['evidenceIds']==(['prior','lead'] if change is None else ['lead'])


@pytest.mark.parametrize('foreign', [False,True])
def test_numeric_row_retains_its_own_caption_without_borrowing_another_source(foreign):
    caption='Table 2: Quantitative results on Dataset-R2, lower error is better. '
    values='Our model 0.11 0.12 0.13 0.14 0.15 0.16.'
    common={'sourceId':'owned','sourceWorkId':'a','sourceVersionId':'a-v1','contentHash':'snapshot',
            'sourceContext':caption+values,'verification':{'literal':'passed'}}
    header={**deepcopy(common),'evidenceId':'caption','quote':caption,
            'location':{'page':3,'offset':0,'sourcePassageStart':0,'sourcePassageEnd':len(caption)}}
    row={**deepcopy(common),'evidenceId':'values','quote':values,
         'location':{'page':3,'offset':0,'sourcePassageStart':len(caption),'sourcePassageEnd':len(caption+values)}}
    if foreign:header['sourceId']='another_source'
    obs={'o':{'obligationId':'o','question':'Dataset-R2的精度数值','requiredSources':['a-v1']}}
    _,bundles=premise_bundles([header,row],obs)
    assert bundles[0]['evidenceIds']==(['values'] if foreign else ['caption','values'])
