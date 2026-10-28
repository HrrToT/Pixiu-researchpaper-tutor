from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.scope_compaction import compact
from services.deep_research.scope_expression import materialize
from services.deep_research.answer_constraints import visible_count
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.contracts import DeepResearchError
from test_deep_research_scope_compaction import packet


def fixture():
    report,audits,response=packet()
    report['claims'][1],audit=materialize({**report['claims'][1],'text':'','scopeExpression':audits[0]['expression']},3)
    return report,[audit],{'claims':[{'claimId':'f','text':'作者报告质量略降。','conditions':{}}]}


def test_only_ordinary_prose_is_sent_for_edit_and_scope_sources_stay_exact():
    report,audits,response=fixture();before=deepcopy((report,audits));joint=Mock();direct=Mock(return_value={'content':json.dumps(response)})
    out,new=compact(report,audits,'300字以内',joint,json.loads,presentation_version=2,expression_version=3,
        fixed_scope_first=True,invoke_fixed=direct)
    assert out and visible_count(out,300,presentation_version=2)<=300
    assert out['claims'][1]==report['claims'][1] and new[0]['expression']==audits[0]['expression']
    assert all(out['claims'][0][k]==report['claims'][0][k] for k in ('kind','evidenceRefs','tableBindings','obligationIds'))
    assert new[0]['verification']=='unchecked' and (report,audits)==before
    inputs=json.loads(direct.call_args.args[0].rsplit('输入：',1)[1])
    assert [c['claimId'] for c in inputs]==['f'] and '固定范围说明（只读' in direct.call_args.args[0]
    direct.assert_called_once();joint.assert_not_called()


def test_new_strategy_is_limited_to_eligible_new_short_factual_outputs():
    from services.deep_research.factual_reasoning import fixed_scope_compaction
    for version in (None,True,'8',7,9):
        assert not fixed_scope_compaction({'factualReasoningContractVersion':version},'300字以内','claim_verification')
    assert fixed_scope_compaction({'factualReasoningContractVersion':8},'300字以内','claim_verification')
    assert not fixed_scope_compaction({'factualReasoningContractVersion':8},'301字以内','claim_verification')
    assert not fixed_scope_compaction({'factualReasoningContractVersion':8},'300字以内','experiment_design')


@pytest.mark.parametrize('mode',['truncated','empty','blank','foreign','extra','oversized','unknown',
    'bad_id','bad_text','bad_conditions'])
def test_bad_edit_never_deletes_points_changes_scope_or_triggers_a_second_request(mode):
    report,audits,response=fixture();joint=Mock()
    if mode=='empty':response={'claims':[]}
    elif mode=='blank':response['claims'][0]['text']=' '
    elif mode=='foreign':response['claims'][0]['claimId']='c'
    elif mode=='extra':response['claims'][0]['kind']='reported'
    elif mode=='oversized':response['claims'][0]['text']='长'*500
    elif mode=='bad_id':response['claims'][0]['claimId']=['f']
    elif mode=='bad_text':response['claims'][0]['text']=42
    elif mode=='bad_conditions':response['claims'][0]['conditions']=[]
    direct=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mode=='truncated' else 'stop'})
    if mode=='unknown':direct.side_effect=DeepResearchError('call_unknown','unknown')
    args=(report,audits,'300字以内',joint,json.loads)
    before=deepcopy((report,audits))
    if mode=='unknown':
        with pytest.raises(DeepResearchError):compact(*args,presentation_version=2,expression_version=3,fixed_scope_first=True,invoke_fixed=direct)
    else:
        assert compact(*args,presentation_version=2,expression_version=3,fixed_scope_first=True,invoke_fixed=direct)[0] is None
    direct.assert_called_once();joint.assert_not_called();assert (report,audits)==before


def test_large_scope_selects_joint_edit_locally_before_any_provider_submission():
    report,audits,response=packet();raw={**report['claims'][1],'text':'','scopeExpression':deepcopy(audits[0]['expression'])}
    raw['scopeExpression']['observedSettings'][0]['value']='未核验的长设置'*80
    report['claims'][1],audit=materialize(raw,3)
    joint=Mock(return_value={'content':json.dumps(response)});direct=Mock()
    out,new=compact(report,[audit],'300字以内',joint,json.loads,presentation_version=2,expression_version=3,
        fixed_scope_first=True,invoke_fixed=direct)
    assert out and new[0]['verification']=='unchecked'
    joint.assert_called_once();direct.assert_not_called()


def test_external_accepted_content_is_readonly_and_consumes_the_same_shared_limit():
    report,audits,response=fixture();accepted=[{'claimId':'kept','kind':'reported','text':'已经接受的内容。','conditions':{},'evidenceRefs':['e']}]
    before=deepcopy(accepted);direct=Mock(return_value={'content':json.dumps(response)})
    out,new=compact(report,audits,'300字以内',Mock(),json.loads,presentation_version=2,expression_version=3,
        fixed_claims=accepted,fixed_scope_first=True,invoke_fixed=direct)
    assert out and accepted==before and [c['claimId'] for c in out['claims']]==['f','c']
    assert visible_count({**out,'claims':accepted+out['claims']},300,presentation_version=2)<=300
    assert [c['claimId'] for c in json.loads(direct.call_args.args[0].rsplit('输入：',1)[1])]==['f']


def test_actual_generation_routes_one_direct_edit_and_keeps_scope_audit_unchecked():
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.runtime import research_model_options
    report,audits,response=fixture();draft=deepcopy(report)
    draft['claims'][1].update(text='',scopeExpression=audits[0]['expression'])
    record={'question':'两点，300字以内','scopeExpressionContractVersion':3,'scopeCompactionContractVersion':1,
        'scopeExpressionReviewContractVersion':3,'reportPresentationContractVersion':2,'factualReasoningContractVersion':8,
        'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    requests=[]
    def invoke(rid,node,prompt,options,**kw):
        requests.append((node,prompt,options));return {'content':json.dumps(draft if node=='synthesize' else response)}
    assert 'error_code' not in make_synthesize_node(invoke,update)({'run_id':'r'})
    assert [r[0] for r in requests]==['synthesize','synthesize_compact']
    assert research_model_options('synthesize_compact',requests[1][2])['reasoning_effort']=='none'
    assert record['state']['reportBody']['claims'][1]==report['claims'][1]
    assert record['state']['synthesisScopeExpressionAudit'][0]['verification']=='unchecked'


def test_repair_batch_identity_and_resume_include_fixed_scope_strategy():
    report,audits,response=fixture();states=[];joint=Mock();direct=Mock(return_value={'content':json.dumps(response)})
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'300字以内',joint,json.loads)
    kwargs={'expression_version':3,'presentation_version':2,'fixed_scope_first':True,'invoke_fixed':direct}
    out=compact_repairs(*args,checkpoint=states.append,**kwargs)
    assert out and states[-1]['scopeExpressionAudit'][0]['expression']==audits[0]['expression']
    direct.assert_called_once();joint.assert_not_called();direct.reset_mock()
    assert compact_repairs(*args,saved=states[-1],**kwargs)==out
    direct.assert_not_called()
    with pytest.raises(DeepResearchError):compact_repairs(*args,saved=states[-1],expression_version=3,presentation_version=2)
    joint.assert_not_called()
