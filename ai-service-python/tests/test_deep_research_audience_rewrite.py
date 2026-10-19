from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from services.deep_research.audience_rewrite import eligible, rewrite_for_beginner, OUTPUT_TOKENS
from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
from services.deep_research.verification import verify_claims


def fixture():
    report = {'sections': [{'title': '核心判断', 'claimIds': ['why', 'how']}], 'claims': [
        {'claimId': 'why', 'kind': 'reported', 'text': '预测概率分布降低局部极小值风险。',
         'conditions': {'范围': '作者的直观示例'}, 'evidenceRefs': ['e'],
         'obligationIds': ['why'], 'detailLevel': 'fulltext'},
        {'claimId': 'how', 'kind': 'inference', 'text': '将观测误差经中间参数反馈至分布。',
         'conditions': {}, 'evidenceRefs': ['e'], 'obligationIds': ['how'], 'detailLevel': 'fulltext'}]}
    evidence = [{'evidenceId': 'e', 'quote': 'The observed error updates a parameter.',
                 'sourceContext': 'Conditional example. The observed error updates a parameter. Not guaranteed.',
                 'sourceWorkId': 'paper', 'sourceVersionId': 'v2', 'accessLevel': 'fulltext',
                 'verification': {'literal': 'passed'}}]
    return report, evidence


def answer(**kwargs):
    return {'content': json.dumps({'claims': [
        {'claimId': 'why', 'text': '先保留几种可能的位置，避免过早认定一个猜测。'},
        {'claimId': 'how', 'text': '把生成图像与观测图像的差异作为调整信号，改变已有参数；后续放置会随之改变。'}]},
        ensure_ascii=False), **kwargs}


def test_short_beginner_answer_is_rewritten_once_without_changing_identity_or_conditions():
    report, evidence = fixture(); before = deepcopy((report, evidence)); sent, states = [], []
    question = '用初学者能懂的话解释，300字以内'
    assert eligible({'audienceRewriteContractVersion': 1, 'question': question}, report, 'direction_survey')
    result = rewrite_for_beginner(report, evidence, question,
        lambda prompt, output: (sent.append((prompt, output)) or answer()), json.loads, checkpoint=states.append)
    assert len(sent) == 1 and sent[0][1] == OUTPUT_TOKENS
    assert result['sections'] == report['sections']
    for old, new in zip(report['claims'], result['claims']):
        assert new['text'] != old['text']
        assert {k:v for k,v in new.items() if k!='text'} == {k:v for k,v in old.items() if k!='text'}
    assert (report,evidence) == before
    assert not verify_claims(result['claims'], evidence)['accepted']  # No style pass becomes factual approval.
    assert states[-1]['status'] == 'received'
    assert rewrite_for_beginner(report, evidence, question, lambda *_:pytest.fail('No paid repeat'),
        json.loads, saved_state=states[-1]) == result


@pytest.mark.parametrize('version', [None, True, 0, 9, '1'])
def test_legacy_or_invalid_contract_never_adds_a_beginner_call(version):
    report,_=fixture()
    assert not eligible({'audienceRewriteContractVersion':version,'question':'给新手解释'}, report, 'direction_survey')


@pytest.mark.parametrize('question', ['解释论文', '详细推导公式', '研究新手教学方法',
                                     '不要面向新手，详细解释', '无需通俗化，给出推导'])
def test_ordinary_or_explicitly_technical_questions_do_not_trigger_extra_calls(question):
    report,_=fixture()
    assert not eligible({'audienceRewriteContractVersion':1,'question':question}, report, 'claim_verification')


@pytest.mark.parametrize('question', ['给新手解释', '请通俗地讲一下', '用初学者能懂的话解释',
                                     'Explain to a beginner', 'Use plain English'])
def test_explicit_audience_requests_are_recognized(question):
    report,_=fixture()
    assert eligible({'audienceRewriteContractVersion':1,'question':question}, report, 'claim_verification')


def test_experiment_configuration_and_proposals_are_excluded_from_wording_editor():
    report,_=fixture(); record={'audienceRewriteContractVersion':1,'question':'给新手解释'}
    assert not eligible(record,report,'experiment_design')
    report['claims'][0].update(kind='proposal', designRole='controls',executionSpec={'parameters':[]})
    assert not eligible(record,report,'direction_survey')


def test_editor_sees_all_original_premises_and_no_uncited_sources():
    report,evidence=fixture(); evidence.append({**evidence[0],'evidenceId':'foreign','quote':'SECRET uncited source'})
    def invoke(prompt,output):
        assert evidence[0]['quote'] in prompt
        assert 'Conditional example.' in prompt and 'Not guaranteed.' in prompt
        assert 'SECRET uncited source' not in prompt and '作者的直观示例' in prompt
        assert 'Fixed conditions use' in prompt and 'characters available' in prompt
        return answer()
    rewrite_for_beginner(report,evidence,'给新手解释，300字以内',invoke,json.loads)


@pytest.mark.parametrize('patch', [
    {'claims':[{'claimId':'why','text':'短'}]},
    {'claims':[{'claimId':'why','text':'短'},{'claimId':'why','text':'重复'}]},
    {'claims':[{'claimId':'why','text':'短','conditions':{}},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'why','text':'短','evidenceRefs':['foreign']},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'why','text':'短','kind':'proposal'},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'why','text':'短','tableBindings':[]},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'foreign','text':'短'},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'why','text':''},{'claimId':'how','text':'短'}]},
    {'claims':[{'claimId':'why','text':'x'*301},{'claimId':'how','text':'短'}]},
    {'claims':[], 'verification':'passed'},
])
def test_invalid_or_overlong_edit_is_saved_but_never_applied_or_retried(patch):
    report,evidence=fixture(); states=[]
    result=rewrite_for_beginner(report,evidence,'给新手解释，300字以内',
        lambda *_:{'content':json.dumps(patch)},json.loads,checkpoint=states.append)
    assert result==report and states[-1]['content']==json.dumps(patch)
    assert rewrite_for_beginner(report,evidence,'给新手解释，300字以内',lambda *_:pytest.fail('No repeat'),
        json.loads,saved_state=states[-1])==report


@pytest.mark.parametrize('response', [answer(finishReason='length'), answer(finish_reason='length'),
                                     {'content':'{"claims":'}, SimpleNamespace(content='not JSON',finish_reason='stop')])
def test_truncation_and_malformed_response_leave_original_for_independent_verification(response):
    report,evidence=fixture()
    assert rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:response,json.loads)==report


def test_capacity_skip_keeps_complete_original_source_instead_of_sending_a_truncated_premise():
    report,evidence=fixture(); evidence[0]['quote']='original source '*4000
    evidence[0]['sourceContext']=evidence[0]['quote']; states=[]
    assert rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:pytest.fail('No send'),
        json.loads,checkpoint=states.append)==report
    assert states[-1]['reason']=='input_capacity'


def test_budget_skip_is_durable_without_spending_the_verification_reserve():
    report,evidence=fixture(); states=[]
    def invoke(*_): raise BudgetExhaustedError('normalTokens',50000,50001)
    assert rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,checkpoint=states.append)==report
    assert states[-1]['reason']=='budget'
    assert rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:pytest.fail('No budget retry'),
        json.loads,saved_state=states[-1])==report


def test_unknown_transport_keeps_frozen_request_and_changed_inputs_cannot_regenerate_it():
    report,evidence=fixture(); states=[]
    def unknown(*_): raise OSError('Unconfirmed transport')
    with pytest.raises(OSError):
        rewrite_for_beginner(report,evidence,'给新手解释',unknown,json.loads,checkpoint=states.append)
    assert states[-1]['status']=='pending'
    with pytest.raises(DeepResearchError, match='原始输入'):
        rewrite_for_beginner(report,evidence,'给新手解释，增加一个问题',lambda *_:pytest.fail('No resend'),
            json.loads,saved_state=states[-1])


def test_frozen_request_is_reused_after_raw_response_checkpoint_failure(tmp_path):
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    report,evidence=fixture(); states=[]; sends=[]
    repo=DeepResearchRepository(str(tmp_path/'calls.sqlite3')); repo.initialize(); repo.create_run({'runId':'r'}); repo.begin_execution('r')
    class Provider:
        def invoke(self,request):
            sends.append(request.prompt)
            return LLMResult('fixture','fixture',answer()['content'],LLMUsage(10,20,30),'stop')
    tracked=TrackedLLMInvoker(Provider(),repo.reserve_call,repo.complete_call)
    def invoke(prompt,output): return tracked('r','synthesize_audience',prompt,{'max_tokens':output})
    def checkpoint(state):
        if state['status']=='received': raise InterruptedError('After settlement before checkpoint')
        states.append(state)
    with pytest.raises(InterruptedError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,checkpoint=checkpoint)
    pending=deepcopy(states[-1]); assert pending['request']['prompt']==sends[0]
    result=rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,saved_state=pending)
    assert result!=report and len(sends)==1
    assert [c['status'] for c in repo.list_calls('r')]==['succeeded']


def test_real_unknown_ledger_blocks_frozen_request_reissue(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    report,evidence=fixture(); states=[]; sends=[]
    repo=DeepResearchRepository(str(tmp_path/'calls.sqlite3')); repo.initialize(); repo.create_run({'runId':'r'}); repo.begin_execution('r')
    class Provider:
        def invoke(self,request):
            sends.append(request.prompt)
            raise LLMProviderError('Unknown',provider='fixture',model='fixture')
    tracked=TrackedLLMInvoker(Provider(),repo.reserve_call,repo.complete_call)
    def invoke(prompt,output): return tracked('r','synthesize_audience',prompt,{'max_tokens':output})
    with pytest.raises(LLMProviderError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,checkpoint=states.append)
    with pytest.raises(UnknownCallError):
        rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,saved_state=states[-1])
    assert len(sends)==1 and repo.list_calls('r')[0]['status']=='unknown'


@pytest.mark.parametrize('changed', [None,0,True,2])
def test_audience_contract_is_immutable_during_a_run(tmp_path,changed):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3')); repo.initialize()
    repo.create_run({'runId':'r','audienceRewriteContractVersion':1})
    with pytest.raises(ValueError,match='Immutable run field'):
        repo.update_run('r',lambda r:{**r,'audienceRewriteContractVersion':changed})


def test_client_cannot_disable_or_expand_server_audience_contract(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3')); repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object())
    try:
        response,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'给新手解释',
            'materials':[],'audienceRewriteContractVersion':0},start_async=False)
        assert repo.require_run(response['runId'])['audienceRewriteContractVersion']==8
    finally: facade.shutdown()


def test_synthesis_graph_runs_editor_for_short_new_answer_and_retains_final_verification_gate():
    from services.deep_research.graph import make_synthesize_node
    report,evidence=fixture(); calls=[]
    record={'question':'用初学者能懂的话解释，300字以内','audienceRewriteContractVersion':1,
            'state':{'outputKind':'direction_survey','evidence':evidence}, 'budget':{}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record)
        return deepcopy(record)
    def invoke(run,node,prompt,options,**kwargs):
        calls.append(node)
        if node=='synthesize':
            drafted=deepcopy(report)
            for c in drafted['claims']: c['evidenceRefs']=['E1']
            return {'content':json.dumps(drafted)}
        assert node=='synthesize_audience' and kwargs.get('use_reserve') is not True
        assert options['max_tokens']==OUTPUT_TOKENS
        return answer()
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert result['report_version_id']=='report_r_v1'
    assert calls==['synthesize','synthesize_audience']
    assert record['state']['audienceRewrite']['status']=='received'
    edited=record['state']['reportBody']
    assert edited['claims'][0]['text']!=report['claims'][0]['text']
    assert edited['claims'][0]['evidenceRefs']==['e']
    assert not verify_claims(edited['claims'],evidence)['accepted']


def test_audience_role_reserves_json_output_in_normal_pool_before_send(tmp_path):
    from unittest.mock import Mock
    from llm.provider import LLMResult,LLMUsage
    from services.deep_research.runtime import research_model_options
    from services.deep_research.tools import TrackedLLMInvoker
    provider=Mock(); reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False)); complete=Mock()
    provider.invoke.return_value=LLMResult('fixture','fixture',answer()['content'],LLMUsage(10,20,30),'stop')
    tracked=TrackedLLMInvoker(provider,reserve,complete,request_options=research_model_options)
    tracked('r','synthesize_audience','draft and sources',{'max_tokens':100})
    request=provider.invoke.call_args.args[0]
    assert request.extra_body['max_tokens']==OUTPUT_TOKENS
    assert request.extra_body['response_format']=={'type':'json_object'}
    assert request.extra_body['thinking']=={'type':'disabled'}
    assert reserve.call_args.kwargs['use_reserve'] is False
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(b'draft and sources')+1024+OUTPUT_TOKENS


def test_real_ledger_budget_denial_does_not_consume_verification_reserve(tmp_path):
    from unittest.mock import Mock
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    report,evidence=fixture(); states=[]
    repo=DeepResearchRepository(str(tmp_path/'calls.sqlite3')); repo.initialize()
    repo.create_run({'runId':'r','budget':{'tokens':50000,'normalTokens':50000,'modelCalls':13}})
    repo.begin_execution('r'); before=deepcopy(repo.require_run('r')['budget'])
    provider=Mock(); tracked=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    def invoke(prompt,output): return tracked('r','synthesize_audience',prompt,{'max_tokens':output})
    assert rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,checkpoint=states.append)==report
    provider.invoke.assert_not_called()
    assert states[-1]['reason']=='budget' and repo.list_calls('r')==[]
    assert repo.require_run('r')['budget']==before


def test_late_editor_is_skipped_before_dispatch_and_not_restarted_after_pause():
    from datetime import datetime,UTC
    from services.deep_research.audience_rewrite import has_time_for_rewrite
    report,evidence=fixture(); states=[]
    record={'budget':{'maxWallClockSeconds':360},'startedAt':'2026-10-16T08:00:00Z'}
    assert has_time_for_rewrite(record,now=datetime(2026,10,16,8,4,30,tzinfo=UTC))
    assert not has_time_for_rewrite(record,now=datetime(2026,10,16,8,4,31,tzinfo=UTC))
    assert rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:pytest.fail('No late edit'),
        json.loads,can_start=False,checkpoint=states.append)==report
    assert states[-1]['reason']=='time'
    assert rewrite_for_beginner(report,evidence,'给新手解释',lambda *_:pytest.fail('No time retry'),
        json.loads,can_start=True,saved_state=states[-1])==report
