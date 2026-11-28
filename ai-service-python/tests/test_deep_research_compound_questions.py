from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.compound_questions import split_questions
from services.deep_research.evidence_requirements import normalize_generated_requirements
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from test_deep_research_imperative_grounding import plan


HUMAN='为什么要渲染深度和表面法线，以及这些图怎样用于几何重建'
PARTS=['为什么要渲染深度和表面法线','这些图怎样用于几何重建']


@pytest.mark.parametrize('human,expected',[(HUMAN,PARTS),
    ('解释为什么要记录误差，并且它怎样更新状态',['解释为什么要记录误差','它怎样更新状态']),
    ('Explain why the model needs depth and normal maps and how these maps produce the output',
     ['Explain why the model needs depth and normal maps','how these maps produce the output']),
    ('为什么需要这种表示，以及怎么用于优化过程',['为什么需要这种表示','怎么用于优化过程']),
    ('解释它是否改变原始表示、为什么需要这些图，以及这些图怎样用于重建',
     ['解释它是否改变原始表示','为什么需要这些图','这些图怎样用于重建']),
    ('What is the input and why is it needed and how does it produce the output',
     ['What is the input','why is it needed','how does it produce the output'])])
def test_joined_questions_become_literal_independent_parts(human,expected):
    assert split_questions(human)==expected
    assert all(part in human for part in expected)


@pytest.mark.parametrize('human',['为什么深度和法线需要联合考虑','如何比较方法A与方法B',
    '比较为什么A更快与如何B更准这两个说法',
    '解释“为什么使用深度，以及怎样得到网格”这个例子',
    "Explain the phrase 'why a model and how a method'",
    '解释 `why one and how another` 这段代码',
    '不要解释为什么这样，以及怎样实现',
    '不是问为什么使用它，以及怎样实现它',
    "Don't explain why a model fails and how it is trained",
    '为什么需要改进，以及无需说明如何实现细节',
    '为什么要A，以及如何实现B，以及为何要C，以及怎样得到D，以及如何完成E'])
def test_entities_examples_negation_and_overflow_are_not_new_deliverables(human):
    assert split_questions(human)==[human]


def test_normalization_keeps_original_question_sources_and_old_protocol():
    original=plan(HUMAN);before=deepcopy(original)
    old,_=normalize_generated_requirements(original,HUMAN,literal_questions=True,literal_imperatives=True,atomic_dimensions=True)
    new,_=normalize_generated_requirements(original,HUMAN,literal_questions=True,literal_imperatives=True,atomic_dimensions=True,compound_questions=True)
    assert len(old[0]['obligations'][0]['completionCriteria'])==1
    o=new[0]['obligations'][0]
    assert [c['requirement'] for c in o['completionCriteria']]==PARTS
    assert all(c['responseType']=='explanation' for c in o['completionCriteria'])
    assert o['question']==HUMAN and o['requestExcerpt']==HUMAN and o['requiredSources']==['paper']
    assert original==before


def test_identification_questions_keep_their_response_type_when_joined_with_explanations():
    human='哪些视图作为输入，以及它们怎样用于训练'
    fixed,_=normalize_generated_requirements(plan(human),human,literal_questions=True,literal_imperatives=True,atomic_dimensions=True,compound_questions=True)
    criteria=fixed[0]['obligations'][0]['completionCriteria']
    assert [c['requirement'] for c in criteria]==['哪些视图作为输入','它们怎样用于训练']
    assert [c['responseType'] for c in criteria]==['identification','explanation']


@pytest.mark.parametrize('version',[3,4])
@pytest.mark.parametrize('human,parts',[(HUMAN,PARTS),
    ('解释它是否改变原始表示、为什么需要这些图，以及这些图怎样用于重建',
     ['解释它是否改变原始表示','为什么需要这些图','这些图怎样用于重建'])])
def test_actual_plan_node_freezes_each_part_without_an_extra_model_request(version,human,parts):
    expected=parts if version==4 else [human]
    record={'question':human,'evidenceCoverageContractVersion':3,'requestGroundingContractVersion':version,
            'planCompletionContractVersion':1,'materials':[{'materialId':'paper'}],
            'state':{'outputKind':'claim_verification'}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps(plan(human),ensure_ascii=False)})
    result=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert not result.get('error_code')
    assert invoke.call_count==1
    assert [c['requirement'] for c in record['state']['plan'][0]['obligations'][0]['completionCriteria']]==expected


@pytest.mark.parametrize('version,missing_added', [(4, False), (5, True)])
def test_short_single_paper_plan_retains_joined_questions_outside_model_excerpts(version, missing_added):
    how = '怎样决定什么时候结束'
    why = '为什么不能只看一个点'
    second_rule = '继续时又怎样决定跳过哪些点'
    computation = '说清两种决定各省了什么计算'
    question = f'给新手解释它{how}、{second_rule}。{computation}，以及{why}。限300字。'
    original = plan(how)
    item = original[0]
    item['searchQuery'] = 'adaptive stopping and pruning'
    first = item['obligations'][0]
    first.update(requestExcerpt=how, purpose='answer_requirement')
    second = {**deepcopy(first), 'obligationId': 'why', 'question': why, 'requestExcerpt': why}
    item['obligations'].append(second)
    record = {'question':question, 'evidenceCoverageContractVersion':3,
              'requestGroundingContractVersion':version, 'planCompletionContractVersion':1,
              'audienceFirstContractVersion':2, 'audienceRewriteContractVersion':9,
              'audiencePublicationBudgetContractVersion':1, 'reportPresentationContractVersion':4,
              'sourcePolicy':{'mode':'task_only'}, 'materials':[{'materialId':'paper'}],
              'state':{'outputKind':'claim_verification'}}

    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return deepcopy(record)

    invoke = Mock(return_value={'content':json.dumps(original,ensure_ascii=False)})
    result = make_plan_node(invoke, update, validate_plan)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count == 1
    obligations = record['state']['plan'][0]['obligations']
    assert len(obligations) == (3 if missing_added else 2)
    assert all(row['requiredSources'] == ['paper'] for row in obligations)
    if missing_added:
        assert obligations[2]['searchQuery'] == item['searchQuery']
        assert [c['requirement'] for c in obligations[2]['completionCriteria']] == [second_rule, computation]
        assert all(c['responseType'] == 'explanation' for c in obligations[2]['completionCriteria'])


def test_quoted_example_does_not_create_an_unassigned_obligation():
    from services.deep_research.compound_questions import retain_unassigned_questions
    question = '解释它怎样完成匹配。例子是“为什么要停止，以及怎样忽略某些点”。'
    original = plan('怎样完成匹配')
    original[0]['obligations'][0].update(purpose='answer_requirement', requestExcerpt='怎样完成匹配')
    assert retain_unassigned_questions(original, question) == (original, [])


def test_multi_item_plan_keeps_missing_how_question_before_a_coordinated_subject():
    from services.deep_research.compound_questions import retain_unassigned_questions

    first = '怎样从分布得到连续位置'
    missing = '位置的导数怎样传回分布'
    last = '拟合损失和局部约束分别控制什么'
    question = f'给新手解释{first}、{missing}，以及{last}。不超过300字。'
    extraction, = plan(first)
    training, = plan(last)
    for item, item_id, target in ((extraction, 'mechanism', first), (training, 'training', last)):
        item.update(itemId=item_id, searchQuery=item_id, dependencies=[])
        item['obligations'][0].update(obligationId=item_id, requestExcerpt=target, purpose='answer_requirement')
    original = [extraction, training]
    repaired, audit = retain_unassigned_questions(original, question, multiple_items=True)
    assert len(audit) == 1
    assert repaired[1] == training and repaired[0]['dependencies'] == extraction['dependencies']
    assert len(original[0]['obligations']) == 1
    added = repaired[0]['obligations'][1]
    assert added['searchQuery'] == 'mechanism'
    assert [(c['requirement'], c['responseType']) for c in added['completionCriteria']] == [(missing, 'explanation')]


def test_repeating_the_whole_question_cannot_supply_both_process_input_and_output():
    from services.deep_research.process_explanations import validate_links
    requirement='这些深度图怎样用于几何重建？'
    link={'input':{'request':requirement},'operation':{'id':'c','field':'text','excerpt':'融合'},
          'output':{'request':requirement}}
    entities={'c':{'text':'把深度图融合为网格。'}};before=deepcopy(link)
    assert not validate_links([link],entities,{'c'},requirement)
    assert validate_links([link],entities,{'c'},requirement,request_spans=True)==['overlapping_process_roles']
    specific={**link,'input':{'request':'深度图'},'output':{'request':'几何重建'}}
    assert not validate_links([specific],entities,{'c'},requirement,request_spans=True)
    assert link==before


@pytest.mark.parametrize('version,has_gap',[(4,False),(5,True)])
def test_final_audit_preserves_old_protocol_but_new_requires_distinct_process_roles(version,has_gap):
    from services.deep_research.final_coverage import audit_final_answer
    from test_deep_research_process_explanations import PLAN,QUESTION,raw,claim
    c=claim('把深度图融合为网格。');sent=[]
    links=[{'input':{'request':QUESTION},'operation':{'id':'c','field':'text','excerpt':'融合'},'output':{'request':QUESTION}}]
    def invoke(run,node,prompt,options,**kwargs):
        sent.append(prompt)
        fixed=json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        return {'content':json.dumps(raw(fixed,links),ensure_ascii=False)}
    audit=audit_final_answer('r',QUESTION,PLAN,[c],[],invoke,json.loads,request_contract=version)
    assert audit['status']=='checked' and bool(audit['gaps']) is has_gap and len(sent)==1
    assert ('do not copy the whole question' in sent[0].lower()) is has_gap


@pytest.mark.parametrize('version,has_gap',[(2,False),(3,True)])
def test_joint_readiness_freezes_and_applies_the_corresponding_role_policy(version,has_gap):
    from services.deep_research.verification import make_evidence
    from test_deep_research_joint_assessment import fixture,Memory,execute,units
    question='这些深度图怎样用于几何重建？';record=fixture(('paper',));record['question']=question
    record['jointEvidenceContractVersion']=version
    o=record['state']['plan'][0]['obligations'][0];o.update(question=question,requestExcerpt=question)
    o['completionCriteria'][0].update(requirement=question,responseType='explanation')
    quote='We fuse depth maps to construct a mesh.'
    record['state']['evidence']=[make_evidence({'workId':'paper','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={'page':3},obligation_ids=[o['obligationId']])]
    def invoke(run,node,prompt,options):
        assert options['max_tokens']==1536
        return {'content':json.dumps([{'unitId':u['unitId'],'ready':True,'evidenceIds':u['evidenceIds'],
            'processLinks':[{'input':{'request':question},'operation':{'id':u['evidenceIds'][0],'field':'quote','excerpt':'fuse'},'output':{'request':question}}]} for u in units(prompt)])}
    assert bool(execute(Memory(record),invoke)['gaps']) is has_gap


@pytest.mark.parametrize('version',[3,4])
def test_bounded_synthesis_uses_compact_question_layout_only_for_new_policy(version):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.compound_questions import DRAFT_GUIDANCE
    from test_deep_research_audience_rewrite import fixture
    report,evidence=fixture();before=deepcopy((report,evidence));sent=[]
    record={'requestGroundingContractVersion':version,'question':HUMAN+'。350字以内。',
            'state':{'outputKind':'claim_verification','evidence':evidence},'budget':{}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return deepcopy(record)
    def invoke(run,node,prompt,options,**kwargs):
        sent.append(prompt);draft=deepcopy(report)
        for c in draft['claims']:c['evidenceRefs']=['E1']
        return {'content':json.dumps(draft)}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert not result.get('error_code') and len(sent)==1
    assert (DRAFT_GUIDANCE in sent[0]) is (version==4)
    assert (report,evidence)==before
