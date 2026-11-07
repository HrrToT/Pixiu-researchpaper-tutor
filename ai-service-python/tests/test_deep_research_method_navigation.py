from copy import deepcopy
import json

import pytest

from services.deep_research.external_sections import spans,select,passages
from services.deep_research.external import _page_passages
from services.deep_research.method_navigation import priority,bundle,requested
from services.deep_research.synthesis_evidence import order_premises
from services.deep_research.verification import make_evidence,verify_claims


def pages():
    return [{'page':1,'text':'TITLE\nA broad overview.\n1 I NTRODUCTION\nWe introduce a method.'},
        {'page':2,'text':'2 A LGORITHM\nThe state is defined as a moving average.\n2.1 U PDATE RULE\nWe update the state.'},
        {'page':3,'text':'3 I NITIALIZATION\nAn initial state causes an early bias.\nWe divide by the accumulated weight.'},
        {'page':4,'text':'4 C ONVERGENCE ANALYSIS\nUnder stated assumptions a bound holds.'},
        {'page':5,'text':'5 E XPERIMENTS\nInitialization initialization update update bias results.'}]


def test_integer_small_caps_are_normalized_before_admission_without_changing_quotes():
    original=pages();before=deepcopy(original);annotated=spans(original,outline=True,normalize_headings=True)
    assert any(p['role']=='method' and '2 A LGORITHM' in p['section'] for p in annotated[1][1])
    assert annotated[2][1][0]['role']=='method' and '3 I NITIALIZATION' in annotated[2][1][0]['section']
    assert annotated[3][1][0]['role']=='other' and annotated[4][1][0]['role']=='other'
    for page,parts in annotated:
        for offset,quote,section,role in passages(page,parts,_page_passages):
            assert page['text'][offset:offset+len(quote)]==quote
    assert original==before
    assert not any(p['role']=='method' for _,parts in spans(original,outline=True) for p in parts)


def test_three_page_cap_finds_actual_method_not_repeated_experiment_keywords():
    selected=select(pages(),'这些统计量各记录什么？ 为什么有初始化偏差？',{'initialization','update','bias'},contract_version=3)
    assert {p['page'] for p,_ in selected}=={1,2,3}
    assert len(selected)==3


def test_numbered_sentences_equations_and_long_text_do_not_become_sections():
    sample=[{'page':1,'text':'1 Algorithm improves accuracy. It has more steps.\n2 x = y\n3 '+('Long '*20)+'\nordinary text'}]
    assert all(p['role']=='unknown' for _,parts in spans(sample,outline=True,normalize_headings=True) for p in parts)


@pytest.mark.parametrize('q',['解释相关工作中的表示','explain traditional methods','报告实验结果','explain reported results','参考文献中的算法','主要结果是什么','what are the main results?'])
def test_background_results_and_bibliography_are_not_reclassified_as_method_requests(q):
    assert not requested(q)


def test_roman_preliminary_and_reference_roles_survive_new_integer_admission():
    from test_deep_research_pdf_outline import pages as roman_pages
    annotated=spans(roman_pages(),outline=True,normalize_headings=True)
    assert all(p['role']=='other' for p in annotated[1][1])
    assert annotated[2][1][0]['role']=='method'
    assert all(p['role']=='references' for p in annotated[-1][1])


def evidence(text,index,*,source='owned',start=0):
    return make_evidence({'workId':source,'versionId':source+'-v1','contentHash':'h','accessLevel':'fulltext'},text,text,
        location={'page':2,'offset':0,'sourcePassageStart':start,'sourcePassageEnd':start+len(text)},obligation_ids=['o']) | {'sourceId':source+'-read','evidenceId':'e'+str(index)}


def test_definition_and_causal_premises_rank_before_overview_and_experiment_names():
    intro=evidence('We introduce a method that improves results.',0)
    definition=evidence('The values are estimates of the moving averages of the measurements.',1)
    cause=evidence('However these averages start from zero, leading to an early bias.',2,start=len(definition['quote']))
    before=deepcopy([intro,definition,cause])
    assert priority(definition,'这些统计量各记录什么','measurement estimates definitions')>priority(intro,'这些统计量各记录什么','measurement estimates definitions')
    selected=bundle([intro,definition,cause],'为什么从零开始会有偏差','initialization estimates bias')
    assert selected==[definition,cause] and [intro,definition,cause]==before


def test_small_cap_background_title_cannot_promote_its_definition_as_a_method_premise():
    background=evidence('The values are estimates of moving averages.',1)
    background['location']['section']='5 R ELATED W ORK'
    method=evidence('The values are estimates of the moving averages of measurements.',2)
    assert priority(background,'这些统计量各记录什么','estimates')<priority(method,'这些统计量各记录什么','estimates')
    assert bundle([background,method],'这些统计量各记录什么','estimates')==[method]


@pytest.mark.parametrize('field',['sourceId','sourceWorkId','sourceVersionId','contentHash'])
def test_adjacent_context_never_crosses_source_or_version_or_missing_identity(field):
    prior=evidence('The quantities record previous observations.',1)
    lead=evidence('These estimates cause a discrepancy because of initialization.',2,start=len(prior['quote']))
    prior[field]='foreign'
    assert bundle([prior,lead],'为什么会有偏差','estimates initialization')==[lead]
    prior[field]=lead[field];lead.pop(field)
    assert bundle([prior,lead],'为什么会有偏差','estimates initialization')==[lead]


def test_new_synthesis_navigation_preserves_source_scope_and_needs_independent_checks():
    rows=[evidence('We introduce a useful method.',i) for i in range(23)]
    core=evidence('The quantities are estimates of moving averages of the observations.',24)
    foreign=evidence('The quantities are estimates of moving averages.',25,source='foreign')
    rows += [core,foreign];before=deepcopy(rows)
    plan=[{'itemId':'i','question':'解释统计量定义','obligations':[{'obligationId':'o','question':'统计量各记录什么',
        'searchQuery':'observations estimates definition','requiredSources':['owned'],
        'completionCriteria':[{'criterionId':'c','requirement':'统计量各记录什么','responseType':'identification'}]}]}]
    old,_=order_premises(rows,plan)
    new,groups=order_premises(rows,plan,criterion_method_navigation=True)
    assert core not in old and core in new
    assert all(foreign['evidenceId'] not in group['evidenceIds'] for group in groups if group['source']=='owned')
    assert len(new)<=20 and rows==before and groups
    claim={'claimId':'c','text':'This interpretation is universally correct.','kind':'reported','evidenceRefs':[core['evidenceId']]}
    assert not verify_claims([claim],[core])['accepted']


def test_joint_readiness_prioritizes_own_criterion_premises_and_keeps_false_verdict_false():
    from test_deep_research_joint_assessment import fixture,Memory,execute,units
    record=fixture(('owned',));record['externalReadingContractVersion']=3
    record['state']['evidence']=[evidence('We evaluate an unrelated benchmark result.',i) for i in range(12)]
    core=evidence('The quantities are estimates of moving averages of observations.',20)
    record['state']['evidence'].append(core)
    o=record['state']['plan'][0]['obligations'][0]
    o.update(question='统计量各记录什么',searchQuery='estimates observations definition',
        completionCriteria=[{'criterionId':'c','requirement':'统计量各记录什么','responseType':'identification'}])
    memory=Memory(record);sent=[]
    def invoke(run,node,prompt,options):
        sent.append(prompt);assert core['quote'] in prompt
        return {'content':json.dumps([{'unitId':u['unitId'],'ready':False,'evidenceIds':[]} for u in units(prompt)])}
    result=execute(memory,invoke)
    assert len(sent)==1 and result['gaps'] and len(sent[0].encode())<=24000
