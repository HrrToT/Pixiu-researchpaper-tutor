"""A trusted low profile changes only the bounded coverage correction request."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.coverage_binding_correction import KEY,OPTION,GUIDANCE
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_coverage_binding_correction import run,policy,Q,PLAN,CLAIMS,links
from test_deep_research_coverage_instructions import inputs


def test_new_profile_keeps_initial_review_exact_and_only_changes_correction_options():
    old,old_calls=run();new,new_calls=run(reasoned=True)
    assert old_calls[0]==new_calls[0] and old_calls[1][1]==new_calls[1][1]
    assert not new['gaps'] and new['coverageBindingCorrectionContractVersion']==2
    assert old['coverageBindingCorrectionContractVersion']==1
    assert new['processBindingCorrection']['inputDigest']!=old['processBindingCorrection']['inputDigest']
    actual=research_model_options(new_calls[1][0],new_calls[1][2])
    previous=research_model_options(old_calls[1][0],old_calls[1][2])
    assert OPTION not in actual and actual['thinking']=={'type':'enabled'} and actual['reasoning_effort']=='low'
    assert actual['max_tokens']==previous['max_tokens']<=3500
    assert research_model_options(new_calls[0][0],new_calls[0][2])['reasoning_effort']=='none'


@pytest.mark.parametrize('node',['verify','verify_repair','synthesize','synthesize_compact','repair_claims','plan'])
def test_private_reasoning_marker_is_rejected_outside_coverage_node_before_reservation(node):
    provider=Mock();reserve=Mock();tracked=TrackedLLMInvoker(provider,reserve,Mock())
    with pytest.raises(ValueError):tracked('r',node,'fixed prompt',{OPTION:True,'max_tokens':3500})
    provider.invoke.assert_not_called();reserve.assert_not_called()


@pytest.mark.parametrize('marker',[None,1,'true'])
def test_marker_type_is_validated_in_both_runtime_and_bare_tracked_dispatch(marker):
    with pytest.raises(ValueError):research_model_options('verify_answer_coverage',{OPTION:marker})
    reserve=Mock();tracked=TrackedLLMInvoker(Mock(),reserve,Mock())
    with pytest.raises(ValueError):tracked('r','verify_answer_coverage','p',{OPTION:marker})
    reserve.assert_not_called()


@pytest.mark.parametrize('cap',[None,True,0,3501,'3500'])
def test_output_cap_cannot_exceed_original_correction_allowance(cap):
    reserve=Mock();tracked=TrackedLLMInvoker(Mock(),reserve,Mock())
    with pytest.raises(ValueError):tracked('r','verify_answer_coverage','p',{OPTION:True,'max_tokens':cap})
    reserve.assert_not_called()


@pytest.mark.parametrize('other',['_short_factual_reasoning','_short_factual_direct_repair','_short_factual_high_synthesis','_short_factual_compaction_reasoning','_short_factual_direct_synthesis'])
def test_correction_profile_cannot_be_combined_with_other_roles(other):
    with pytest.raises(ValueError):research_model_options('verify_answer_coverage',{OPTION:True,other:True})


def test_false_marker_is_removed_without_changing_old_effective_options():
    args={'max_tokens':3000,'temperature':0.0}
    assert research_model_options('verify_answer_coverage',{**args,OPTION:False})==research_model_options('verify_answer_coverage',args)


@pytest.mark.parametrize('version',[1,2])
def test_actual_graph_sets_profile_only_on_one_correction_callback(version):
    from services.deep_research.graph import make_verify_node
    record={**policy(),KEY:version,'coverageInputContractVersion':1,'question':Q,'state':{'outputKind':'claim_verification','reportBody':{'claims':deepcopy(CLAIMS)},'plan':PLAN,'evidence':[]},'budget':{}}
    sent=[]
    def update(_id,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append((node,prompt,options))
        if prompt.startswith(GUIDANCE):
            data=json.loads(prompt.split('Frozen review inputs:\n',1)[1]);target=data['targets'][0]
            rows=[{'obligationId':target['obligationId'],'checkId':target['checkId'],'status':'covered','processLinks':links(),'reason':'Actual operation connects the input and output.'}]
        else:
            req=inputs(prompt)['requirements'];rows=[{'obligationId':o['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'text'}],'reason':'Initial judgement.','processLinks':links('wrong' if o['obligationId']=='o' else '深度图')} for c in o['checks']]} for o in req]
        return {'content':json.dumps(rows)}
    make_verify_node(lambda *_:{'accepted':deepcopy(CLAIMS),'rejected':[]},None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(sent)==2 and not record['state']['verifiedReport']['answerCoverage']['gaps']
    assert OPTION not in sent[0][2] and (sent[1][2].get(OPTION) is True) is (version==2)
    wire=research_model_options('verify_answer_coverage',sent[1][2]);assert wire['reasoning_effort']==('low' if version==2 else 'none')
    assert record['state']['reportBody']=={'claims':CLAIMS}


def test_profile_dispatch_is_fingerprinted_and_reserved_before_provider(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from llm.provider import LLMResult,LLMUsage
    repo=DeepResearchRepository(tmp_path/'calls.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':Q,'state':{},'budget':{'maxModelCalls':2,'maxTokens':50000,'maxWallClockSeconds':180,'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r')
    reserve=Mock(wraps=repo.reserve_call);requests=[]
    def reply(request):
        assert reserve.call_count==len(requests)+1;requests.append(request)
        return LLMResult(provider='fixture',model='fixture',content='[]',usage=LLMUsage(10,10,20),finish_reason='stop')
    provider=Mock();provider.invoke.side_effect=reply
    tracked=TrackedLLMInvoker(provider,reserve,repo.complete_call,run_record_fn=repo.require_run)
    tracked('r','verify_answer_coverage','same prompt',research_model_options('verify_answer_coverage',{'max_tokens':3500,'temperature':0.0}))
    tracked('r','verify_answer_coverage','same prompt',{OPTION:True,'max_tokens':3500,'temperature':0.0})
    assert len(requests)==2 and OPTION not in requests[1].extra_body
    assert requests[1].extra_body['reasoning_effort']=='low' and requests[1].extra_body['max_tokens']==3500
    assert reserve.call_args_list[0].kwargs['args_digest']!=reserve.call_args_list[1].kwargs['args_digest']
    assert all(c.kwargs['budget_delta']['tokens']>=3500 for c in reserve.call_args_list)
