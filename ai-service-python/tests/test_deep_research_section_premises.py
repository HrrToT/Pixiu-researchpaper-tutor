from copy import deepcopy
import json
import pytest
from services.deep_research.section_premises import requested,bundle
from services.deep_research.synthesis_evidence import order_premises,fit_premises
from services.deep_research.request_context import ResearchQuestion


def packet():
    before='4.4 Previous method\nEarlier discussion.\n'
    a='4.5 FREQUENCY-AWARE MASKING\nA learned mask is weighted by training-view frequency.\n'
    b='Higher frequency makes removal harder. Similar training and test views are assumed.\n'
    after='\n4.6 TRAINING OBJECTIVES\nUnrelated loss details.'
    first=before+a;second=b+after
    sources=[{'sourceId':sid,'workId':'p','ownerMaterialId':'p','versionId':'v','contentHash':'pdf-hash',
              'accessLevel':'fulltext','text':text,'location':{'page':7,'offset':offset}}
             for sid,text,offset in [('s1',first,0),('s2',second,len(first))]]
    rows=[{'evidenceId':eid,'sourceId':sid,'sourceWorkId':'p','ownerMaterialId':'p',
           'sourceVersionId':'v','quote':quote,'verification':{'literal':'passed'},
           'location':{'page':7,'offset':offset,'sourcePassageStart':start,'sourcePassageEnd':end}}
          for eid,sid,quote,offset,start,end in [('a','s1',a,0,len(before),len(first)),('b','s2',b,len(first),0,len(b))]]
    return rows,sources


def test_only_explicit_human_section_requests_activate_priority():
    assert requested('读取arXiv:2503.00357v2，解释第4.5节。')==['4.5']
    assert requested('Read Section 4.5 and sec. 6.2.')==['4.5','6.2']
    assert requested('不要读第4.5节。解释第4.6节。')==['4.6']
    assert not requested('解释arXiv:2503.00357v2和3DGS')
    assert not requested('引文：“第4.5节”')
    assert not requested(ResearchQuestion('模型建议读取第4.5节',['只解释压缩机制']))


def test_complete_section_across_fragments_preserves_literal_units_and_version():
    rows,sources=packet();before=deepcopy((rows,sources))
    assert bundle(rows,sources,'p',['4.5'])==rows
    assert (rows,sources)==before
    assert not bundle(rows,sources,'other',['4.5'])
    assert not bundle(rows,sources,'p',['4.6']) # no next heading establishes its end


@pytest.mark.parametrize('fault',['version','pdf_hash','owner','offset_gap','overlap','quote','unverified','missing_unit','duplicate_source','duplicate_evidence','unclosed'])
def test_no_cross_version_page_join_or_incomplete_section_approval(fault):
    rows,sources=packet()
    if fault=='version':sources[1]['versionId']='v2'
    if fault=='pdf_hash':sources[1]['contentHash']='different-pdf'
    if fault=='owner':sources[1]['ownerMaterialId']='other'
    if fault=='offset_gap':sources[1]['location']['offset']+=1
    if fault=='overlap':sources[1]['location']['offset']-=1
    if fault=='quote':rows[1]['quote']='not the original'
    if fault=='unverified':rows[1]['verification']['literal']='unchecked'
    if fault=='missing_unit':rows.pop()
    if fault=='duplicate_source':sources.append(deepcopy(sources[1]))
    if fault=='duplicate_evidence':rows.append(deepcopy(rows[0]))
    if fault=='unclosed':sources[1]['text']=sources[1]['text'].split('4.6')[0]
    assert not bundle(rows,sources,'p',['4.5'])


def test_new_priority_precedes_generic_overviews_and_links_same_item_reference():
    rows,sources=packet()
    lead={**deepcopy(rows[0]),'evidenceId':'overview','sourceId':'other',
          'quote':'Our contributions include: • compression; • efficiency.',
          'location':{'section':'Proposed method'}}
    plan=[{'obligations':[{'obligationId':'one','question':'解释第4.5节机制','requiredSources':['p']},
                         {'obligationId':'two','question':'这种设计依赖什么前提','requiredSources':['p']}]}]
    old,old_bundles=order_premises([lead,*rows],plan,read_sources=sources,mechanism_overview=True)
    new,new_bundles=order_premises([lead,*rows],plan,read_sources=sources,mechanism_overview=True,section_targets=['4.5'])
    assert old[0]==lead and new[:2]==rows
    assert all(b['evidenceIds']==['a','b'] for b in new_bundles)
    assert all(b['evidenceIds']==['overview'] for b in old_bundles)
    rendered,selected,missing=fit_premises(new,json.dumps,new_bundles,max_bytes=3000)
    assert not missing and all(row in selected for row in rows)
    _,_,missing=fit_premises(new,json.dumps,new_bundles,max_bytes=20)
    assert missing


def test_referential_context_never_overrides_another_explicit_section_or_plan_item():
    rows,sources=packet()
    lead={**deepcopy(rows[0]),'evidenceId':'overview','sourceId':'other',
          'quote':'Our contributions include: • compression; • efficiency.',
          'location':{'section':'Proposed method'}}
    first={'obligationId':'first','question':'解释第4.5节机制','requiredSources':['p']}
    for question,other_item in [('这种设计在第4.6节的目标是什么',False),('这种设计依赖什么前提',True)]:
        second={'obligationId':'second','question':question,'requiredSources':['p']}
        plan=[{'obligations':[first,second]}] if not other_item else [{'obligations':[first]},{'obligations':[second]}]
        _,bundles=order_premises([lead,*rows],plan,read_sources=sources,mechanism_overview=True,section_targets=['4.5'])
        target=next(b for b in bundles if b['obligationId']=='second')
        assert target['evidenceIds']==['overview']
