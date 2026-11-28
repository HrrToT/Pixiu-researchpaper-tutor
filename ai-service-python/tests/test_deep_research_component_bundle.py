from copy import deepcopy
import pytest
from services.deep_research.mechanism_sources import component_bundle
from services.deep_research.synthesis_evidence import order_premises,fit_premises
import json


def packet():
    a='We introduce our approach. Our contributions include:\n• A spatial context model. '
    b='• A channel context model. • A masking procedure.'
    text=a+b
    source={'sourceId':'s','workId':'p','ownerMaterialId':'p','versionId':'v','text':text,
            'accessLevel':'fulltext','location':{'section':'Introduction'}}
    rows=[{'evidenceId':str(i),'sourceId':'s','sourceWorkId':'p','ownerMaterialId':'p',
           'sourceVersionId':'v','quote':quote,'verification':{'literal':'passed'},
           'location':{'section':'Introduction','sourcePassageStart':start,'sourcePassageEnd':stop}}
          for i,quote,start,stop in [(0,a,0,len(a)),(1,b,len(a),len(text))]]
    return rows,[source]


def test_component_list_retains_separate_original_units_and_identity():
    rows,sources=packet();before=deepcopy((rows,sources))
    result=component_bundle(rows,sources,'p')
    assert result==rows and (rows,sources)==before
    assert all(result[i] is rows[i] for i in range(2))


@pytest.mark.parametrize('fault',['foreign','version','owner','literal','text','gap','duplicate','source_duplicate','large'])
def test_component_bundle_cannot_join_unmatched_or_incomplete_sources(fault):
    rows,sources=packet()
    if fault=='foreign':rows[1]['sourceWorkId']='other'
    if fault=='version':rows[1]['sourceVersionId']='v2'
    if fault=='owner':sources[0]['ownerMaterialId']='other'
    if fault=='literal':rows[1]['verification']['literal']='unchecked'
    if fault=='text':rows[1]['quote']='different quotation'
    if fault=='gap':rows[1]['location']['sourcePassageStart']+=1
    if fault=='duplicate':rows[1]['evidenceId']=rows[0]['evidenceId']
    if fault=='source_duplicate':sources+=deepcopy(sources)
    if fault=='large':sources[0]['text']+='x'*2000
    assert component_bundle(rows,sources,'p')==[]


def test_new_allocation_bundles_components_without_changing_legacy_order_or_capacity():
    rows,sources=packet()
    lead={**deepcopy(rows[0]),'evidenceId':'method','sourceId':'m','quote':'Our method encodes attributes.',
          'location':{'section':'Proposed method'}}
    plan=[{'obligations':[{'obligationId':'o','question':'解释机制','requiredSources':['p']}]}]
    old,old_bundles=order_premises([lead,*rows],plan,mechanism_overview=True,read_sources=sources)
    new,bundles=order_premises([lead,*rows],plan,mechanism_overview=True,read_sources=sources,mechanism_components=True)
    assert old[0]==lead and old_bundles[0]['evidenceIds']==['method']
    assert new[:2]==rows and bundles[0]['evidenceIds']==['0','1']
    def render(items):return json.dumps(items,ensure_ascii=False)
    complete=fit_premises(new,render,bundles,max_bytes=3000)
    assert complete[1][:2]==rows
    # A tight input cannot silently keep half a required list as complete.
    limited=fit_premises(new,render,bundles,max_bytes=len(render([rows[0]]).encode())+1)
    assert limited[2]
