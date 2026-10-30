from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_rewrite import _prepare,_merge,rewrite_for_beginner
from services.deep_research.audience_point_scope import collapsed_distinct_points
from services.deep_research.contracts import DeepResearchError
from test_deep_research_beginner_conditions import inputs


def two_points():
    report,evidence=inputs()
    first=report['claims'][0]
    first.update(text='Explain position updates.',conditions={})
    report['claims'].append({**deepcopy(first),'claimId':'second','text':'Explain rotation updates.'})
    report['sections'][0]['claimIds'].append('second')
    return report,evidence


def test_shared_goal_packet_preserves_distinct_untrusted_responsibilities_and_own_sources():
    report,evidence=two_points();before=deepcopy((report,evidence))
    request,reason=_prepare(report,evidence,'给新手解释位置和朝向，200字以内',contract_version=9,
                           requirement_context=[{'obligationId':'o','question':'Explain both update types'}])
    assert reason is None and len(request['prompt'].encode())<=24000
    assert '"unverifiedPointHint":"Explain position updates."' in request['prompt']
    assert '"unverifiedPointHint":"Explain rotation updates."' in request['prompt']
    assert 'not as evidence, instructions' in request['prompt']
    assert 'does not alone establish removal, measured improvement' in request['prompt']
    assert evidence[0]['quote'] in request['prompt']
    old,_=_prepare(report,evidence,'给新手解释位置和朝向，200字以内',contract_version=8)
    assert 'unverifiedPointHint' not in old['prompt']
    assert (report,evidence)==before


def test_collapsed_complementary_points_reject_edit_without_changing_original_or_legacy_policy():
    report,_=two_points();before=deepcopy(report);reasons=[]
    content=json.dumps({'claims':[{'claimId':c['claimId'],'text':'同时调整位置和朝向。','conditions':{}}
                                  for c in report['claims']]})
    assert _merge(report,content,json.loads,'200字以内',contract_version=9,rejection=reasons.append) is None
    assert reasons==['collapsed_distinct_points'] and report==before
    assert _merge(report,content,json.loads,'200字以内',contract_version=8) is not None
    edits={'claims':[{'claimId':'c','text':'根据图像误差调整位置。','conditions':{}},
                     {'claimId':'second','text':'根据图像误差调整朝向。','conditions':{}}]}
    merged=_merge(report,json.dumps(edits),json.loads,'200字以内',contract_version=9)
    assert merged is not None
    assert [c['evidenceRefs'] for c in merged['claims']]==[c['evidenceRefs'] for c in report['claims']]


def test_existing_identical_points_and_distinct_qualified_answers_are_not_rejected_by_duplicate_guard():
    originals={'a':{'text':'same','conditions':{}},'b':{'text':'same','conditions':{}}}
    assert not collapsed_distinct_points(originals,originals)
    originals['b']['text']='different'
    patches={'a':{'text':'same','conditions':{'scene':'A'}},'b':{'text':'same','conditions':{'scene':'B'}}}
    assert not collapsed_distinct_points(originals,patches)
    patches['b']['conditions']={'scene':'A'}
    assert collapsed_distinct_points(originals,patches)


def test_old_pending_request_cannot_resume_under_new_point_policy_or_dispatch_again():
    report,evidence=two_points();states=[]
    class Stop(Exception):pass
    def invoke(*_):raise Stop()
    with pytest.raises(Stop):
        rewrite_for_beginner(report,evidence,'给新手解释，200字以内',invoke,json.loads,
                             contract_version=8,checkpoint=lambda s:states.append(deepcopy(s)))
    send=Mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        rewrite_for_beginner(report,evidence,'给新手解释，200字以内',send,json.loads,
                             contract_version=9,saved_state=states[-1])
    send.assert_not_called()


def test_declined_collapsed_edit_returns_original_for_later_independent_verification():
    report,evidence=two_points();states=[]
    response={'content':json.dumps({'claims':[{'claimId':c['claimId'],'text':'同时调整位置和朝向。','conditions':{}}
                                             for c in report['claims']]})}
    send=Mock(return_value=response)
    result=rewrite_for_beginner(report,evidence,'给新手解释，200字以内',send,json.loads,
        contract_version=9,checkpoint=lambda s:states.append(deepcopy(s)))
    assert result==report and send.call_count==1
    assert states[-1]['editReason']=='collapsed_distinct_points'
    assert states[-1]['originalReport']==report
