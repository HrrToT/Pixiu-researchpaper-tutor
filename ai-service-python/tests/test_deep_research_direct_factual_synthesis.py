"""Direct drafting changes a role, not the evidence or publication gate."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.factual_reasoning import (
    request_options, DIRECT_SYNTHESIS_OPTION, OPTION, HIGH_SYNTHESIS_OPTION)
from services.deep_research.runtime import research_model_options


def record(version=10):
    return {'factualReasoningContractVersion':version,
            'materialSnapshot':{'materialRefs':['a','b']}}


def test_v10_changes_only_bounded_initial_draft_mode_with_identical_output_cap():
    old=request_options(record(9),'比较两篇论文的条件和结果，500字以内。','paper_comparison')
    new=request_options(record(),'比较两篇论文的条件和结果，500字以内。','paper_comparison')
    assert new=={**old,DIRECT_SYNTHESIS_OPTION:True}
    before=research_model_options('synthesize',old);after=research_model_options('synthesize',new)
    assert after=={**before,'thinking':{'type':'disabled'},'reasoning_effort':'none'}
    assert before['max_tokens']==after['max_tokens']==8192
    assert after['response_format']==before['response_format']=={'type':'json_object'}
    assert DIRECT_SYNTHESIS_OPTION not in after


@pytest.mark.parametrize('node',['verify','repair_claims','synthesize_compact','extract'])
def test_direct_synthesis_flag_cannot_disable_independent_reviews_or_change_repairs(node):
    old=request_options(record(9),'300字以内','claim_verification')
    new=request_options(record(),'300字以内','claim_verification')
    assert research_model_options(node,{**new,'max_tokens':4096})==research_model_options(node,{**old,'max_tokens':4096})


@pytest.mark.parametrize('version',[None,True,'10',0,11])
def test_profile_requires_an_explicit_supported_server_version(version):
    assert request_options(record(version),'300字以内','claim_verification')=={}


@pytest.mark.parametrize('question,kind',[
    ('301字以内','claim_verification'),('701字以内','paper_comparison'),
    ('详细比较','paper_comparison'),('300字以内','experiment_design'),('300字以内','direction_survey')])
def test_output_and_human_limit_eligibility_does_not_expand(question,kind):
    assert request_options(record(),question,kind)==request_options(record(9),question,kind)=={}


def test_request_is_reserved_before_send_same_budget_different_fingerprint_and_cached_once():
    from services.deep_research.tools import TrackedLLMInvoker
    provider=Mock();provider.invoke.return_value=LLMResult('fixture','fixture','{}',LLMUsage(8,2,10),finish_reason='stop')
    reserve=Mock(side_effect=[({'callId':'old','reservationToken':'r'},False),
                             ({'callId':'new','reservationToken':'s'},False),
                             ({'callId':'new','result':{'content':'settled'}},True)])
    complete=Mock();tracked=TrackedLLMInvoker(provider,reserve,complete,request_options=research_model_options)
    old=request_options(record(9),'500字以内','paper_comparison')
    new=request_options(record(),'500字以内','paper_comparison');original=deepcopy(new)
    tracked('r','synthesize','same complete evidence prompt',old,use_reserve=True)
    tracked('r','synthesize','same complete evidence prompt',new,use_reserve=True)
    first,second=reserve.call_args_list[:2]
    assert first.kwargs['budget_delta']==second.kwargs['budget_delta']
    assert first.kwargs['args_digest']!=second.kwargs['args_digest']
    assert provider.invoke.call_args.args[0].extra_body['thinking']=={'type':'disabled'}
    assert provider.invoke.call_args.args[0].extra_body['max_tokens']==8192
    assert all(not k.startswith('_short_') for k in provider.invoke.call_args.args[0].extra_body)
    assert tracked('r','synthesize','same complete evidence prompt',new,use_reserve=True)['content']=='settled'
    assert provider.invoke.call_count==2 and complete.call_count==2 and new==original


def test_actual_synthesis_still_fails_closed_on_truncation_with_one_call_and_no_draft():
    from services.deep_research.graph import make_synthesize_node
    current={**record(),'question':'比较两篇论文，500字以内。','state':{'outputKind':'paper_comparison','evidence':[]}}
    def update(rid,change,**kwargs):
        nonlocal current
        current=change(current);return deepcopy(current)
    invoke=Mock(return_value={'content':'null','rawContent':'{"claims":[','finishReason':'length'})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert result=={'error_code':'invalid_synthesis_response'} and invoke.call_count==1
    assert 'reportBody' not in current['state'] and 'verifiedReport' not in current['state']
    options=research_model_options('synthesize',invoke.call_args.args[3])
    assert options['thinking']=={'type':'disabled'} and options['max_tokens']==8192


@pytest.mark.parametrize('flags',[
    {DIRECT_SYNTHESIS_OPTION:1,OPTION:True},
    {DIRECT_SYNTHESIS_OPTION:True},
    {DIRECT_SYNTHESIS_OPTION:True,OPTION:True,HIGH_SYNTHESIS_OPTION:True},
])
def test_ambiguous_or_unscoped_direct_profiles_are_rejected(flags):
    with pytest.raises(ValueError,match='direct factual synthesis'):
        research_model_options('synthesize',flags)


def test_current_compaction_scope_and_existing_draft_ids_are_not_relaxed():
    from services.deep_research.factual_reasoning import compaction_options,fixed_scope_compaction,explicit_compaction_scope
    for function in (compaction_options,fixed_scope_compaction,explicit_compaction_scope):
        assert function(record(),'300字以内','claim_verification')==function(record(9),'300字以内','claim_verification')


def test_saved_v9_cannot_switch_to_direct_mode_after_a_request_exists(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','factualReasoningContractVersion':9})
    before=repo.require_run('r')
    with pytest.raises(ValueError,match='Immutable'):
        repo.update_run('r',lambda r:{**r,'factualReasoningContractVersion':10})
    assert repo.require_run('r')==before
