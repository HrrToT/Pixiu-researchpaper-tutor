from copy import deepcopy
import json

import pytest

from services.deep_research.audience_rewrite import eligible, rewrite_for_beginner, OUTPUT_TOKENS, _merge
from services.deep_research.contracts import DeepResearchError, UnknownCallError
from services.deep_research.verification import make_evidence, verify_claims


def inputs():
    quote='We update position and rotation from the image error and carry the base points to the next frame.'
    e=make_evidence({'workId':'paper','versionId':'v1','contentHash':'hash','accessLevel':'fulltext'},quote,quote,
                    location={'page':3},obligation_ids=['o'])
    c={'claimId':'c','kind':'reported','text':'这里有4个自由度。',
       'conditions':{'实现':'4个参数，证据E1'},'evidenceRefs':[e['evidenceId']],
       'obligationIds':['o'],'detailLevel':'fulltext'}
    return {'claims':[c],'sections':[{'title':'解释','claimIds':['c']}]},[e]


def response(text='根据生成图像与真实图像的差异调整位置和朝向，再把基础点传到下一帧。',conditions=None,**extra):
    return {'content':json.dumps({'claims':[{'claimId':'c','text':text,'conditions':conditions or {},**extra}]},ensure_ascii=False)}


def test_version_two_can_remove_unverified_count_and_alias_in_conditions_without_changing_audit_or_sources():
    report,evidence=inputs();before=deepcopy((report,evidence));states=[];sent=[]
    requirements=[{'obligationId':'o','question':'通俗解释调整什么以及传给下一帧什么','requiredSources':['paper']}]
    result=rewrite_for_beginner(report,evidence,'给新手解释，200字以内',
        lambda p,o:(sent.append((p,o)) or response()),json.loads,contract_version=2,
        requirement_context=requirements,checkpoint=states.append)
    assert result['claims'][0]['conditions']=={}
    assert '4' not in result['claims'][0]['text'] and 'E1' not in result['claims'][0]['text']
    for key in ('claimId','kind','evidenceRefs','obligationIds','detailLevel'):
        assert result['claims'][0][key]==report['claims'][0][key]
    assert states[-1]['originalReport']==report and states[-1]['version']==2
    assert (report,evidence)==before and result['sections']==report['sections']
    assert sent[0][1]==OUTPUT_TOKENS and len(sent[0][0].encode('utf8'))<=24000
    assert evidence[0]['quote'] in sent[0][0] and 'Human requirements:' in sent[0][0]
    assert not verify_claims(result['claims'],evidence)['accepted']  # Wording edit is not approval.
    assert rewrite_for_beginner(report,evidence,'给新手解释，200字以内',
        lambda *_:pytest.fail('No paid repeat'),json.loads,contract_version=2,requirement_context=requirements,
        saved_state=states[-1])==result


@pytest.mark.parametrize('text,conditions',[('无依据地提高99倍。',{}),('描述动作。',{'结果':'提高99倍'})])
def test_new_numeric_claims_in_either_editable_field_still_fail_independent_verification(text,conditions):
    report,evidence=inputs()
    edited=rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:response(text,conditions),json.loads,contract_version=2)
    checked=verify_claims(edited['claims'],evidence,lambda *_:[{'claimId':'c','status':'passed'}])
    assert not checked['accepted'] and checked['rejected'][0]['reason']=='numeric_mismatch'


def test_table_edit_can_only_select_original_bindings_never_invent_or_retarget_them():
    report,evidence=inputs()
    bindings=[{'evidenceId':evidence[0]['evidenceId'],'rowNumber':2,'groupIndex':0,'metric':'FPS','value':'32'},
              {'evidenceId':evidence[0]['evidenceId'],'rowNumber':3,'groupIndex':0,'metric':'FPS','value':'64'}]
    report['claims'][0]['tableBindings']=deepcopy(bindings)
    result=_merge(report,response(retainedTableBindingIndexes=[1])['content'],json.loads,'给新手解释',contract_version=2)
    assert result['claims'][0]['tableBindings']==[bindings[1]]
    assert report['claims'][0]['tableBindings']==bindings
    # The selected cell is still checked against the own original quote/table,
    # not approved because the editor returned a valid index.
    assert not verify_claims(result['claims'],evidence)['accepted']


@pytest.mark.parametrize('indexes',[[True],[-1],[2],[0,0],['0'],None,{'index':0}])
def test_invalid_original_binding_indexes_reject_entire_edit(indexes):
    report,evidence=inputs()
    report['claims'][0]['tableBindings']=[{'evidenceId':evidence[0]['evidenceId'],'rowNumber':1}]
    assert _merge(report,response(retainedTableBindingIndexes=indexes)['content'],json.loads,
                  '给新手解释',contract_version=2) is None


@pytest.mark.parametrize('extra',[{'kind':'proposal'},{'evidenceRefs':['foreign']},{'claimId':'foreign'},
                                {'obligationIds':[]},{'retainedTableBindingIndexes':[]}])
def test_editor_cannot_change_identity_scope_kind_or_obligation_labels(extra):
    report,_=inputs()
    assert _merge(report,response(**extra)['content'],json.loads,'给新手解释',contract_version=2) is None


def test_total_length_includes_rewritten_conditions_and_invalid_response_preserves_original():
    report,evidence=inputs();states=[]
    result=rewrite_for_beginner(report,evidence,'给新手解释，100字以内',
        lambda *_:response('短句',{'条件':'长'*110}),json.loads,contract_version=2,checkpoint=states.append)
    assert result==report and states[-1]['status']=='received'
    assert '长'*110 in states[-1]['content'] and states[-1]['originalReport']==report


@pytest.mark.parametrize('change',['requirements','version','original_audit','question'])
def test_pending_request_is_frozen_across_contract_and_human_requirements(change):
    report,evidence=inputs();states=[];requirements=[{'obligationId':'o','question':'解释动作'}]
    def unknown(*_): raise OSError('Unknown transport')
    with pytest.raises(OSError):
        rewrite_for_beginner(report,evidence,'给新手解释',unknown,json.loads,contract_version=2,
                             requirement_context=requirements,checkpoint=states.append)
    saved=deepcopy(states[-1]);version=2;question='给新手解释'
    if change=='requirements': requirements[0]['question']='新增问题'
    elif change=='version': version=1
    elif change=='original_audit': saved['originalReport']['claims'][0]['conditions']={}
    else: question+='，再解释一个点'
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report,evidence,question,lambda *_:pytest.fail('No resend'),json.loads,
                             contract_version=version,requirement_context=requirements,saved_state=saved)


def test_actual_unknown_ledger_request_is_not_reissued(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    repo=DeepResearchRepository(str(tmp_path/'calls.sqlite3'));repo.initialize();repo.create_run({'runId':'r'});repo.begin_execution('r')
    report,evidence=inputs();sent=[];states=[]
    class Provider:
        def invoke(self,request):
            sent.append(request.prompt)
            raise LLMProviderError('Unknown transport',provider='fixture',model='fixture')
    tracked=TrackedLLMInvoker(Provider(),repo.reserve_call,repo.complete_call)
    def invoke(p,o): return tracked('r','synthesize_audience',p,{'max_tokens':o})
    with pytest.raises(LLMProviderError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=2,checkpoint=states.append)
    with pytest.raises(UnknownCallError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=2,saved_state=states[-1])
    assert len(sent)==1 and repo.list_calls('r')[0]['status']=='unknown'


def test_version_two_remains_explicitly_requested_factual_only():
    report,_=inputs();record={'audienceRewriteContractVersion':2,'question':'给新手解释'}
    assert eligible(record,report,'direction_survey')
    assert not eligible({**record,'question':'专业推导'},report,'direction_survey')
    assert not eligible(record,report,'experiment_design')
    report['claims'][0]['kind']='proposal'
    assert not eligible(record,report,'direction_survey')


def test_graph_passes_literal_requirements_and_keeps_original_draft_without_marking_edit_verified():
    from services.deep_research.graph import make_synthesize_node
    report,evidence=inputs();calls=[]
    requirement={'obligationId':'o','question':'通俗解释调整什么和传给下一帧什么','requiredSources':['paper']}
    record={'question':'给新手解释，200字以内','audienceRewriteContractVersion':2,
            'state':{'outputKind':'direction_survey','evidence':evidence,'plan':[{'obligations':[requirement]}]},'budget':{}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record)
        return deepcopy(record)
    def invoke(run,node,prompt,options,**kwargs):
        calls.append(node)
        if node=='synthesize':
            draft=deepcopy(report);draft['claims'][0]['evidenceRefs']=['E1']
            return {'content':json.dumps(draft)}
        assert node=='synthesize_audience' and requirement['question'] in prompt
        assert options['max_tokens']==OUTPUT_TOKENS
        return response()
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert result['report_version_id']=='report_r_v1' and calls==['synthesize','synthesize_audience']
    assert record['state']['audienceRewrite']['version']==2
    assert record['state']['audienceRewrite']['originalReport']['claims'][0]['conditions']==report['claims'][0]['conditions']
    edited=record['state']['reportBody']
    assert edited['claims'][0]['conditions']=={} and edited['claims'][0]['evidenceRefs']==[evidence[0]['evidenceId']]
    assert 'verifiedReport' not in record['state']
    assert not verify_claims(edited['claims'],evidence)['accepted']
