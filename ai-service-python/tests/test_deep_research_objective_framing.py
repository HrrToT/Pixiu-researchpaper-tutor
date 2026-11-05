from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.mechanism_grounding import (
    DRAFT_GUIDANCE, GUIDANCE, OUTCOME_GUIDANCE, guidance, review_policy, strengthened,
)
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims
from test_deep_research_quantity_surface_labels import pair


@pytest.mark.parametrize('version,policy', [(None,False),(True,False),(1,False),(2,True),(3,2),(4,False)])
def test_review_policy_preserves_old_protocols(version,policy):
    record={'factualReviewContractVersion':version}
    assert review_policy(record) is policy or type(policy) is int and review_policy(record)==policy
    assert strengthened(record) is (type(version) is int and version==3)


def test_new_review_is_bounded_in_size_and_does_not_override_the_actual_verdict():
    claim,evidence=pair('约束确保所有法线准确对齐。','We must ensure that all elements are aligned. We minimize a normal consistency loss.')
    before=deepcopy((claim,evidence))
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'Objective does not establish an achieved guarantee'}])})
    check=BudgetedSemanticChecker(invoke,'r',mechanism_grounding=2)
    assert not verify_claims([claim],[evidence],check)['accepted']
    prompt=invoke.call_args.kwargs['prompt']
    assert OUTCOME_GUIDANCE in prompt and evidence['quote'] in prompt and claim['text'] in prompt
    assert len(OUTCOME_GUIDANCE.encode())<=len(GUIDANCE.encode())
    assert (claim,evidence)==before and invoke.call_count==1
    assert guidance(True)==GUIDANCE and guidance(False)==''


def test_proposals_and_genuine_proofs_keep_their_existing_semantics():
    claim,evidence=pair('拟增加一个一致性项，尚未实施。');claim['kind']='proposal'
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'fixture verdict'}])})
    BudgetedSemanticChecker(invoke,'r',mechanism_grounding=2)([claim],[evidence])
    prompt=invoke.call_args.kwargs['prompt']
    assert 'needs NO quotation proving that' in prompt and 'preserve genuine theorems' in prompt.lower()


def test_partitioned_review_uses_same_policy_in_both_existing_requests():
    from test_deep_research_partitioned_scope_review import inputs,checker_for
    claim,expression,record,evidence=inputs()
    checker,calls=checker_for(claim,expression,record,evidence)
    checker._mechanism_grounding=lambda:2
    assert checker([claim],evidence)[0]['status']=='passed'
    assert len(calls)==2 and all(OUTCOME_GUIDANCE in call['prompt'] for call in calls)


@pytest.mark.parametrize('enabled',[False,True])
def test_synthesis_and_beginner_edit_share_guidance_before_size_admission(enabled):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_audience_rewrite import fixture,answer
    report,evidence=fixture();before=deepcopy((report,evidence));sent=[]
    record={'question':'用初学者能懂的话解释，300字以内','audienceRewriteContractVersion':1,
            'factualReviewContractVersion':3 if enabled else 2,
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
    assert all((DRAFT_GUIDANCE in prompt) is enabled for _,prompt in sent)
    assert (report,evidence)==before
    assert not verify_claims(record['state']['reportBody']['claims'],evidence)['accepted']


def test_pending_audience_request_cannot_change_framing_or_resend():
    from services.deep_research.audience_rewrite import rewrite_for_beginner
    from test_deep_research_audience_rewrite import fixture
    report,evidence=fixture();states=[]
    def unknown(*args):raise OSError('unknown transport')
    with pytest.raises(OSError):
        rewrite_for_beginner(report,evidence,'给新手解释',unknown,json.loads,checkpoint=lambda s:states.append(deepcopy(s)))
    send=Mock()
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report,evidence,'给新手解释',send,json.loads,saved_state=states[-1],objective_framing=True)
    send.assert_not_called()


def test_repair_preserves_original_evidence_and_pending_request_identity():
    from services.deep_research.repair import _prepare_repair,repair_rejected
    from test_deep_research_factual_redraft import inputs
    c,e,checks,requirements=inputs();before=deepcopy((c,e,checks));states=[]
    old=_prepare_repair({'claims':[c]},checks,[e],'Explain')
    new=_prepare_repair({'claims':[c]},checks,[e],'Explain',objective_framing=True)
    assert DRAFT_GUIDANCE not in old['prompt'] and DRAFT_GUIDANCE in new['prompt']
    assert new['allowed']==old['allowed'] and new['originals']==old['originals'] and e['quote'] in new['prompt']
    def unknown(*args):raise OSError('unknown transport')
    with pytest.raises(OSError):
        repair_rejected({'claims':[c]},checks,[e],'Explain',unknown,json.loads,checkpoint=lambda s:states.append(deepcopy(s)))
    send=Mock()
    with pytest.raises(DeepResearchError):
        repair_rejected({'claims':[c]},checks,[e],'Explain',send,json.loads,batch_state=states[-1],objective_framing=True)
    send.assert_not_called();assert (c,e,checks)==before
