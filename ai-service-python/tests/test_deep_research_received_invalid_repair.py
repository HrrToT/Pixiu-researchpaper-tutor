from copy import deepcopy
import json
from unittest.mock import Mock,patch
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair import repair_rejected
from services.deep_research.graph import make_publish_node
from services.deep_research.verification import verify_claims
from test_deep_research_repair_verification_failure import fixture,coverage
from test_deep_research_absence_scope import fixture as absence_fixture


def repair_inputs():
    c={'claimId':'c','kind':'reported','text':'unsupported','evidenceRefs':[]}
    return {'claims':[c]},{'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}


@pytest.mark.parametrize('content',['', 'null', '{}', '{broken', None])
def test_received_invalid_body_is_checkpointed_once_and_never_redispatched(content):
    report,checks=repair_inputs();states=[];invoke=Mock(return_value={'content':content,'finishReason':'stop'})
    assert repair_rejected(report,checks,[],'question',invoke,json.loads,
        strict_response=True,checkpoint=states.append)==[]
    assert invoke.call_count==1
    saved=states[-1]
    assert saved['responseError']=={'code':'invalid_repair_response','responseState':'received_invalid','batch':0}
    assert saved['results']=={'0':[]} and 'pending' not in saved
    assert saved['stop']['reason']=='received_invalid'
    no_dispatch=Mock(side_effect=AssertionError('No replay dispatch'))
    assert repair_rejected(report,checks,[],'question',no_dispatch,json.loads,
        strict_response=True,batch_state=saved)==[]
    no_dispatch.assert_not_called()


def test_valid_empty_array_is_an_explicit_abstention_not_an_invalid_response():
    report,checks=repair_inputs();states=[]
    assert repair_rejected(report,checks,[],'question',lambda _: {'content':'[]'},json.loads,
        strict_response=True,checkpoint=states.append)==[]
    assert 'responseError' not in states[-1] and 'stop' not in states[-1]


def test_unknown_transport_is_not_reclassified_as_received_invalid_or_retried():
    report,checks=repair_inputs();states=[]
    def unknown(_): raise OSError('unknown transport outcome')
    with pytest.raises(OSError):
        repair_rejected(report,checks,[],'question',unknown,json.loads,strict_response=True,checkpoint=states.append)
    assert 'pending' in states[-1] and 'responseError' not in states[-1]
    with pytest.raises(DeepResearchError,match='不一致'):
        repair_rejected(report,checks,[],'question',Mock(),json.loads,batch_state=states[-1])


def test_legacy_null_handling_and_pending_identity_remain_unchanged():
    report,checks=repair_inputs();states=[]
    assert repair_rejected(report,checks,[],'question',lambda _: {'content':'null'},json.loads,
        checkpoint=states.append)==[]
    assert 'responseError' not in states[-1]


def test_graph_preserves_initial_verified_content_and_distinguishes_execution_failure():
    get,update,node,dispatch,rewrite=fixture()
    update('r',lambda r:{**r,'repairProgressContractVersion':2})
    rewrite.return_value={'content':'null','finishReason':'stop','structuredOutput':{'receivedShape':'invalid_json'}}
    with patch('services.deep_research.final_coverage.audit_final_answer',return_value=coverage()):
        assert node({'run_id':'r'})['claim_ids']==['keep']
        saved=deepcopy(get());saved['state'].pop('verifiedReport');saved['state'].pop('repairCompleted')
        update('r',lambda _:saved)
        assert node({'run_id':'r'})['claim_ids']==['keep']
    assert rewrite.call_count==1 and dispatch.call_count==0
    assert get()['state']['repairStatus']=='response_invalid'
    assert get()['state']['repairResponseError']['responseState']=='received_invalid'
    publish=Mock(return_value=({'publicationId':'p'},True))
    assert make_publish_node(publish,update)({'run_id':'r'})['outcome']=='partial'
    assert '修订结果未能解析' in publish.call_args.kwargs['payload']['limitations']
    assert [c['claimId'] for c in publish.call_args.kwargs['payload']['claims']]==['keep']


def test_nominal_condition_key_routes_to_semantics_but_its_value_is_still_checked():
    c,e=absence_fixture('当前证据不足以证明其他条件仍有效。')
    c['conditions']={'未验证范围':'仅基于已报告的数据集与指标'}
    before=deepcopy(c);reject=Mock(return_value=[{'claimId':'c','status':'failed'}])
    assert verify_claims([c],[e],reject,absence_scope_version=5)['rejected'][0]['reason']=='semantic_unresolved'
    reject.assert_called_once()
    assert c==before and not verify_claims([c],[e],absence_scope_version=5)['accepted']
    assert verify_claims([c],[e],absence_scope_version=4)['rejected'][0]['reason']=='absence_not_established'
    c['conditions']['未验证范围']='作者未验证其他条件'
    reject.reset_mock()
    assert verify_claims([c],[e],reject,absence_scope_version=5)['rejected'][0]['reason']=='absence_not_established'
    reject.assert_not_called()
