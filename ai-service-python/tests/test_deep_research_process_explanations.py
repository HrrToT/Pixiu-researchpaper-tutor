from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.process_explanations import required,fields,validate_links,DRAFT_GUIDANCE
from services.deep_research.request_coverage import contract,normalize

QUESTION='这些深度图怎样用于几何重建？'
PLAN=[{'itemId':'i','question':QUESTION,'obligations':[{'obligationId':'o','question':QUESTION,
    'completionCriteria':[{'criterionId':'how','requirement':QUESTION,'responseType':'explanation'}]}]}]


def claim(text):
    return {'claimId':'c','text':text,'conditions':{},'kind':'reported','evidenceRefs':['e']}


def link(identity='c',field='text',operation='融合',output='三角网格'):
    return {'input':{'request':'深度图'},'operation':{'id':identity,'field':field,'excerpt':operation},
            'output':{'id':identity,'field':field,'excerpt':output}}


def raw(fixed,links):
    return [{'obligationId':o['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered',
        'bindings':[{'claimId':'c','field':'text'}],'reason':'Fixture coverage decision',
        **({'processLinks':deepcopy(links)} if c.get('processRequired') else {})} for c in o['checks']]} for o in fixed]


@pytest.mark.parametrize('text',[QUESTION,'How are depth maps used for geometry reconstruction?',
    '请解释具体处理流程','怎样计算这项误差','算法如何运行'])
def test_literal_process_requests_are_recognized(text):
    assert required(text)


@pytest.mark.parametrize('text',['为什么需要深度图','是否能说明这些图怎样用于重建',
    '如何评价论文的训练结果','How to interpret training results?','How many scenes are evaluated?',
    '报告重建性能','解释训练结果'])
def test_outcomes_counts_interpretation_and_evidence_uncertainty_do_not_invent_a_workflow(text):
    assert not required(text)


@pytest.mark.parametrize('text', ['接收端如何重建场景？', '如何压缩场景表示？',
                                  'How does the decoder reconstruct the scene?', 'How do they encode the image?'])
def test_transformation_questions_opt_in_without_changing_legacy_detection(text):
    assert not required(text)
    assert required(text, transformation_processes=True)


@pytest.mark.parametrize('text', ['如何判断重建是否可靠？', '能否说明接收端如何重建场景？',
                                  '请报告实际重建误差。', 'How to evaluate reconstruction quality?',
                                  '如何测量重建误差？', 'How well does it reconstruct the scene?'])
def test_transformation_policy_still_distinguishes_judgment_from_a_process(text):
    assert not required(text, transformation_processes=True)


@pytest.mark.parametrize('opted_in', [False, True])
def test_reconstruction_requests_use_the_same_process_rule_at_draft_readiness_and_final_audit(opted_in):
    from services.deep_research.final_coverage import audit_final_answer
    from services.deep_research.process_explanations import drafting_enabled
    from services.deep_research.verification import make_evidence
    from test_deep_research_joint_assessment import fixture, Memory, execute, units

    question = '接收端如何重建场景？'
    record = fixture(('paper',))
    record.update(question=question, jointEvidenceContractVersion=4, requestCoverageContractVersion=5)
    if opted_in:
        record['processExplanationVocabularyVersion'] = 1
    obligation = record['state']['plan'][0]['obligations'][0]
    obligation.update(question=question, requestExcerpt=question)
    obligation['completionCriteria'][0].update(requirement=question, responseType='explanation')
    body = '接收端使用生成模型重建场景。'
    record['state']['evidence'] = [make_evidence(
        {'workId':'paper','versionId':'paper-v1','contentHash':'h','accessLevel':'fulltext'},
        body, body, location={'page':4}, obligation_ids=[obligation['obligationId']])]

    def assess(_run, _node, prompt, _options):
        rows = units(prompt)
        assert all(bool(unit.get('processRequired')) is opted_in for unit in rows)
        return {'content': json.dumps([{'unitId': unit['unitId'], 'ready': True,
                                        'evidenceIds': unit['evidenceIds']} for unit in rows])}

    assert drafting_enabled(record) is opted_in
    memory = Memory(record)
    assert bool(execute(memory, assess)['gaps']) is opted_in
    assert bool(execute(memory, lambda *_: pytest.fail('A settled assessment must not be resent'))['gaps']) is opted_in

    def audit(_run, _node, prompt, _options, **_kwargs):
        fixed = json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        assert all(bool(check.get('processRequired')) is opted_in for row in fixed for check in row['checks'])
        return {'content': json.dumps(raw(fixed, []), ensure_ascii=False)}

    verdict = audit_final_answer('r', question, record['state']['plan'], [claim(body)], [], audit, json.loads,
                                 request_contract=5, transformation_processes=opted_in)
    assert bool(verdict['gaps']) is opted_in


def test_opted_in_reconstruction_allows_distinct_answer_spans_when_the_operation_is_present():
    question = '如何重建场景？'
    fixed = contract([{'obligations':[{'obligationId':'o','question':question}]}], question,
                     process_explanations=True, transformation_processes=True)
    answer = claim('多视角深度图经融合得到三角网格。')
    roles = [{'input': {'id':'c','field':'text','excerpt':'多视角深度图'},
              'operation': {'id':'c','field':'text','excerpt':'融合'},
              'output': {'id':'c','field':'text','excerpt':'三角网格'}}]
    verdict, = normalize(raw(fixed, roles), fixed, process_explanations=True,
                         distinct_roles=True, claims=[answer])
    assert verdict['status'] == 'covered'


def test_purpose_and_performance_cannot_supply_the_operation_in_a_covered_answer():
    c=claim('这些深度图用于几何重建，并达到了较好的精度。');fixed=contract(PLAN,QUESTION,process_explanations=True)
    links=[{'input':{'request':'深度图'},'operation':{'id':'c','field':'text','excerpt':'用于几何重建'},'output':{'request':'几何重建'}}]
    original=deepcopy((c,fixed,links));result=normalize(raw(fixed,links),fixed,process_explanations=True,claims=[c])
    assert result[0]['status']=='partial' and result[0]['processAudits'][0]['errors']==['purpose_or_result_not_operation']
    assert result[0]['processAudits'][0]['reportedStatus']=='covered'
    assert '实际操作' in result[0]['gapDetail']['missingContent']
    assert (c,fixed,links)==original


def test_context_can_supply_unambiguous_inputs_without_forcing_repetition_or_scientific_approval():
    c=claim('将多视角深度图融合为三角网格。');links=[link()];fixed=contract(PLAN,QUESTION,process_explanations=True)
    assert not validate_links(links,{'c':fields(c)},{'c'},QUESTION)
    result=normalize(raw(fixed,links),fixed,process_explanations=True,claims=[c])
    assert result[0]['status']=='covered'
    from services.deep_research.verification import verify_claims
    assert not verify_claims([c],[])['accepted']
    partial=raw(fixed,links);partial[0]['checks'][0]['status']='partial'
    assert normalize(partial,fixed,process_explanations=True,claims=[c])[0]['status']=='partial'


@pytest.mark.parametrize('change',['source_as_answer','unknown','unquoted','request_operation','overlap','bare_use'])
def test_unbound_or_tautological_roles_never_establish_a_process(change):
    c=claim('将多视角深度图融合为三角网格。');links=[link()]
    if change=='source_as_answer':links[0]['operation'].update(id='E1',field='quote')
    elif change=='unknown':links[0]['operation']['id']='foreign'
    elif change=='unquoted':links[0]['operation']['excerpt']='降采样'
    elif change=='request_operation':links[0]['operation']={'request':'用于'}
    elif change=='overlap':links[0]['input']={'id':'c','field':'text','excerpt':'深度图融合'}
    else:c['text']='使用深度图形成三角网格。';links[0]['operation']['excerpt']='使用'
    assert validate_links(links,{'c':fields(c)},{'c'},QUESTION)


def test_old_request_protocol_is_unchanged_and_new_missing_bindings_do_not_reuse_old_coverage():
    c=claim('这些图用于重建，效果很好。');old=contract(PLAN,QUESTION);new=contract(PLAN,QUESTION,process_explanations=True)
    response=raw(old,[])
    assert normalize(response,old)[0]['status']=='covered'
    assert normalize(response,new,process_explanations=True,claims=[c]) is None


def test_actual_final_audit_keeps_a_process_gap_even_when_model_claims_covered():
    from services.deep_research.final_coverage import audit_final_answer
    c=claim('这些图用于几何重建，并提高了精度。');sent=[]
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append(prompt)
        fixed=json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        return {'content':json.dumps(raw(fixed,[]),ensure_ascii=False)}
    result=audit_final_answer('r',QUESTION,PLAN,[c],[],invoke,json.loads,request_contract=4)
    assert result['status']=='checked' and result['requestCoverageContractVersion']==4
    assert any(g['obligationId']=='o' for g in result['gaps'])
    assert len(sent)==1 and 'processLinks' in sent[0]


def test_joint_readiness_needs_a_bound_source_operation_with_original_output_allowance():
    from services.deep_research.verification import make_evidence
    from test_deep_research_joint_assessment import fixture,Memory,execute,units
    record=fixture(('paper',));record['question']=QUESTION;record['jointEvidenceContractVersion']=2
    o=record['state']['plan'][0]['obligations'][0];o.update(question=QUESTION,requestExcerpt=QUESTION)
    o['completionCriteria'][0].update(requirement=QUESTION,responseType='explanation')
    quote='We fuse depth maps to construct a mesh.'
    e=make_evidence({'workId':'paper','versionId':'paper-v1','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={'page':4},obligation_ids=[o['obligationId']])
    record['state']['evidence']=[e];before=deepcopy(record)
    def invoke(run,node,prompt,options):
        assert options['max_tokens']==1536
        return {'content':json.dumps([{'unitId':u['unitId'],'ready':True,'evidenceIds':u['evidenceIds'],
            'processLinks':[{'input':{'request':'深度图'},'operation':{'id':u['evidenceIds'][0],'field':'quote','excerpt':'fuse'},
                             'output':{'id':u['evidenceIds'][0],'field':'quote','excerpt':'mesh'}}]} for u in units(prompt)])}
    memory=Memory(record);assert not execute(memory,invoke)['gaps'];assert record==before
    memory=Memory(record)
    def invalid(run,node,prompt,options):
        return {'content':json.dumps([{'unitId':u['unitId'],'ready':True,'evidenceIds':u['evidenceIds'],'processLinks':[]} for u in units(prompt)])}
    assert execute(memory,invalid)['gaps']


@pytest.mark.parametrize('phase',['audience','repair'])
def test_unknown_request_cannot_switch_process_policy_and_resend(phase):
    from services.deep_research.contracts import DeepResearchError
    states=[]
    def unknown(*args):raise OSError('unknown transport')
    if phase=='audience':
        from services.deep_research.audience_rewrite import rewrite_for_beginner
        from test_deep_research_audience_rewrite import fixture
        report,evidence=fixture()
        def run(invoke,**kw):return rewrite_for_beginner(report,evidence,QUESTION,invoke,json.loads,**kw)
    else:
        from services.deep_research.repair import repair_rejected
        from test_deep_research_factual_redraft import inputs
        c,e,checks,_=inputs()
        def run(invoke,**kw):return repair_rejected({'claims':[c]},checks,[e],QUESTION,invoke,json.loads,**kw)
    with pytest.raises(OSError):run(unknown,checkpoint=lambda s:states.append(deepcopy(s)))
    send=Mock()
    with pytest.raises(DeepResearchError):run(send,**({'saved_state':states[-1]} if phase=='audience' else {'batch_state':states[-1]}),process_explanations=True)
    send.assert_not_called()


@pytest.mark.parametrize('version',[3,4])
def test_synthesis_and_beginner_edit_receive_process_guidance_only_under_new_contract(version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_audience_rewrite import fixture,answer
    report,evidence=fixture();before=deepcopy((report,evidence));sent=[]
    record={'question':QUESTION+'请给初学者解释，300字以内',
            'audienceRewriteContractVersion':1,'requestCoverageContractVersion':version,
            'state':{'outputKind':'direction_survey','evidence':evidence},'budget':{}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return deepcopy(record)
    def invoke(run,node,prompt,options,**kwargs):
        sent.append((node,prompt))
        if node=='synthesize':
            draft=deepcopy(report)
            for c in draft['claims']:c['evidenceRefs']=['E1']
            return {'content':json.dumps(draft)}
        return answer()
    assert not make_synthesize_node(invoke,update)({'run_id':'r'}).get('error_code')
    assert [node for node,_ in sent]==['synthesize','synthesize_audience']
    assert all((DRAFT_GUIDANCE in prompt) is (version==4) for _,prompt in sent)
    assert (report,evidence)==before


def test_repair_guidance_preserves_actual_sources_and_permissions():
    from services.deep_research.repair import _prepare_repair
    from test_deep_research_factual_redraft import inputs
    c,e,checks,_=inputs();before=deepcopy((c,e,checks))
    old=_prepare_repair({'claims':[c]},checks,[e],QUESTION)
    new=_prepare_repair({'claims':[c]},checks,[e],QUESTION,process_explanations=True)
    assert DRAFT_GUIDANCE not in old['prompt'] and DRAFT_GUIDANCE in new['prompt']
    assert new['allowed']==old['allowed'] and new['originals']==old['originals']
    assert e['quote'] in new['prompt'] and (c,e,checks)==before
