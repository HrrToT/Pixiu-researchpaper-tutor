from unittest.mock import Mock
import json
import pytest
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.mechanism_grounding import GUIDANCE
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('enabled',[False,True])
def test_mechanism_guidance_is_opt_in_and_not_a_semantic_approval(enabled):
    c,e=pair('约束相对预测差异。','The penalty minimizes pairwise differences among predicted depths.')
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'The actual source still decides support.'}])})
    verdicts=BudgetedSemanticChecker(invoke,'r',mechanism_grounding=enabled)([c],[e])
    assert invoke.call_count==1 and verdicts[0]['status']=='failed'
    assert (GUIDANCE in invoke.call_args.kwargs['prompt']) is enabled
    assert e['quote'] in invoke.call_args.kwargs['prompt']
    assert invoke.call_args.kwargs['use_reserve'] is True


def test_new_review_retains_unexecuted_proposal_choice_exception():
    c,e=pair('拟采用四组对照，尚未运行。');c['kind']='proposal'
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'Not approved by this prompt-contract fixture.'}])})
    BudgetedSemanticChecker(invoke,'r',mechanism_grounding=True)([c],[e])
    prompt=invoke.call_args.kwargs['prompt']
    assert 'needs NO quotation proving that' in prompt and GUIDANCE in prompt
    assert 'unexecuted design choices' in prompt


@pytest.mark.parametrize('enabled',[False,True])
def test_partitioned_review_keeps_guidance_in_both_existing_requests(enabled):
    from test_deep_research_partitioned_scope_review import inputs,checker_for
    claim,expression,record,evidence=inputs()
    checker,calls=checker_for(claim,expression,record,evidence)
    checker._mechanism_grounding=lambda:enabled
    result=checker([claim],evidence)[0]
    assert result['status']=='passed' and len(calls)==2
    assert all((GUIDANCE in call['prompt']) is enabled for call in calls)
    assert all(call['use_reserve'] is True for call in calls)
