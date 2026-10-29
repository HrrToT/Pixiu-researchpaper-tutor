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


@pytest.mark.parametrize('question',[
    '解释第5节中两个约束分别约束什么',
    'What does Section 5 constrain?',
    '第4.1节中的2D为何能表示三维场景',
])
def test_explicit_section_priority_does_not_require_mechanism_keywords(question):
    from services.deep_research.section_premises import priority_enabled
    record={'sectionPremisesContractVersion':1,'question':question,
            'state':{'outputKind':'claim_verification'}}
    assert priority_enabled(record)
    assert not priority_enabled({k:v for k,v in record.items() if k!='sectionPremisesContractVersion'})
    assert not priority_enabled({**record,'sectionPremisesContractVersion':True})
    assert not priority_enabled({**record,'state':{'outputKind':'experiment_design'}})


def test_section_priority_uses_human_scope_and_does_not_enable_negated_or_quoted_sections():
    from services.deep_research.section_premises import priority_enabled
    r={'sectionPremisesContractVersion':1,'state':{'outputKind':'claim_verification'}}
    for question in ['不要读第5节。解释整篇论文。','引文：“第5节”','读取arXiv:2403.17888v3']:
        assert not priority_enabled({**r,'question':question})


@pytest.mark.parametrize('suffix,expected',[
    ('，不做性能排名或实验设计。',True),
    ('，但要比较与旧方法的优劣。',False),
    ('，并核查作者的结论。',False),
    ('，给出具体数值。',False),
    ('，不要比较，但要验证更好。',False),
])
def test_explanation_guidance_does_not_hide_requested_check_or_comparison(suffix,expected):
    from services.deep_research.section_premises import explanation_only
    r={'sectionPremisesContractVersion':1,'question':'解释第5节两个约束分别约束什么'+suffix,
       'state':{'outputKind':'claim_verification'}}
    assert explanation_only(r) is expected
    assert not explanation_only({**r,'state':{'outputKind':'paper_comparison'}})


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_section_priority_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释第5节',
            'sectionPremisesContractVersion':replacement},start_async=False)
        assert run['sectionPremisesContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'sectionPremisesContractVersion':replacement})
    finally:facade.shutdown()


def test_section_explanation_drafting_omits_unrequested_verdict_but_keeps_checks_and_schema():
    from services.deep_research.factual_template import build
    from services.deep_research.comparison_reasoning import GUIDANCE
    r={'sectionPremisesContractVersion':1,'comparisonReasoningContractVersion':4,
       'claimCheckContractVersion':9,'question':'解释第5节的两个约束',
       'state':{'outputKind':'claim_verification'}}
    def render(record):
        return build(record,record['question'],'claim_verification',350,4,[],[],{},'EVIDENCE','TABLES')
    new=render(r);old=render({**r,'sectionPremisesContractVersion':0})
    assert GUIDANCE in old and GUIDANCE not in new
    assert 'Bind every factual clause to its own supplied E citations' in new
    assert 'No unknown values' in new and 'tableBindings' in new
    assert 'Every claim has these exact fields' in new
    assert GUIDANCE in render({**r,'question':'解释第5节，并比较效果'})
