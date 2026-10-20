from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.experiment_template import REASONING_OPTION,request_options
from services.deep_research.graph import make_synthesize_node
from services.deep_research.runtime import research_model_options
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_experiment_shared_grammar import record


def test_new_complete_experiment_uses_same_output_cap_and_call_count_with_low_reasoning():
    old=record();new={**old,'experimentDraftContractVersion':2}
    assert request_options(old,'experiment_design')=={}
    assert request_options(new,'experiment_design')=={REASONING_OPTION:True}
    assert request_options(new,'paper_comparison')=={}
    prior=research_model_options('synthesize',{})
    options=research_model_options('synthesize',request_options(new,'experiment_design'))
    assert options=={**prior,'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    assert options['max_tokens']==prior['max_tokens']==16384 and REASONING_OPTION not in options
    with pytest.raises(ValueError):research_model_options('verify',{REASONING_OPTION:True})


def test_private_design_basis_does_not_become_a_source_or_public_claim_and_no_extra_model_stage():
    current=record();current['experimentDraftContractVersion']=2
    basis={'sourceFacts':[{'topic':'UNVERIFIED PRIVATE PLAN','evidenceRefs':['E1'],'scope':'unverified'}],
        'protocol':{'intervention':'private proposed operation'},'unresolved':[]}
    body={'designBasis':basis,'sections':[{'title':'指标','claimIds':['c']}],
        'claims':[{'claimId':'c','kind':'proposal','designRole':'metrics','text':'A proposed observable.',
            'evidenceRefs':[],'conditions':{},'obligationIds':['o']}]}
    original=deepcopy(body)
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    invoke=Mock(return_value={'content':json.dumps(body)})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert 'error_code' not in result and invoke.call_count==1
    assert invoke.call_args.args[3][REASONING_OPTION] is True
    assert 'Fill private designBasis BEFORE claims' in invoke.call_args.args[2]
    stored=current['state']['reportBody'];audit=current['state']['experimentDraftingAudit']
    assert 'designBasis' not in stored and 'UNVERIFIED PRIVATE PLAN' not in json.dumps(stored)
    assert audit['basis']==basis and audit['verification']=='unchecked'
    assert stored['claims'][0]['evidenceRefs']==[] and 'verification' not in stored['claims'][0]
    assert current['state']['evidence'][0]['verification']['semantic']=='unchecked'
    assert body==original


def test_truncated_reasoned_design_is_failure_without_fallback_or_extra_call():
    current=record();current['experimentDraftContractVersion']=2
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    invoke=Mock(return_value={'content':'partial','finishReason':'length'})
    assert make_synthesize_node(invoke,update)({'run_id':'r'})=={'error_code':'invalid_synthesis_response'}
    assert invoke.call_count==1 and not current['state'].get('reportBody')


@pytest.mark.parametrize('configured',[True,False])
def test_same_output_reservation_precedes_send_and_unknown_protection_is_unchanged(configured):
    from llm.provider import LLMResult,LLMUsage
    provider=Mock();provider.invoke.return_value=LLMResult(content='{}',provider='fixture',model='fixture',usage=LLMUsage(8,2,10))
    reserve=Mock(return_value=({'callId':'c','reservationToken':'r'},False));complete=Mock()
    tracked=TrackedLLMInvoker(provider,reserve,complete,request_options=research_model_options if configured else None)
    tracked('r','synthesize','exact source and complete schema',{REASONING_OPTION:True})
    options=provider.invoke.call_args.args[0].extra_body
    assert options['max_tokens']==16384 and options['reasoning_effort']=='low'
    assert reserve.call_args.kwargs['budget_delta']['tokens']==len(b'exact source and complete schema')+1024+16384
    identity=reserve.call_args.kwargs['args_digest']
    reserve.return_value=({'callId':'c','result':{'content':'saved actual response'}},True)
    assert tracked('r','synthesize','exact source and complete schema',{REASONING_OPTION:True})['content']=='saved actual response'
    assert provider.invoke.call_count==1 and reserve.call_args.kwargs['args_digest']==identity
