from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.scope_expression import materialize,review_expression,guidance
from services.deep_research.scope_expression_review import context_for_record
from services.deep_research.scope_compaction import compact
from services.deep_research.repair import repair_rejected
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.contracts import DeepResearchError
from test_deep_research_quantified_scope import quantified


@pytest.mark.parametrize('quantifier,word',[('all','普遍成立'),('exists','存在')])
def test_concise_display_preserves_exact_expression_and_independent_review_proposition(quantifier,word):
    raw=quantified(quantifier);raw['scopeExpression']['observedSettings'].append(
        {'subject':'方法A','attribute':'平台','value':'GPU X（配置*）'})
    before=deepcopy(raw);legacy,old_audit=materialize(raw,2);current,audit=materialize(raw,3)
    assert word in current['text'] and current['text'].startswith('已报告设置：')
    assert len(current['text'])<len(legacy['text'])
    assert audit['expression']==old_audit['expression']==raw['scopeExpression']
    assert review_expression(audit['expression'],3)==review_expression(old_audit['expression'],2)
    assert audit['verification']=='unchecked' and raw==before
    for field in ('kind','evidenceRefs','conditions'):assert current[field]==legacy[field]
    assert 'GPU X（配置*）' in current['text'] and '66%' in current['text'] and '0.01' in current['text']
    record={'scopeExpressionContractVersion':3,'scopeExpressionReviewContractVersion':3,
        'state':{'synthesisScopeExpressionAudit':[audit]}}
    assert context_for_record(record,[current])
    assert not context_for_record(record,[legacy])
    wrong=deepcopy(record);wrong['state']['synthesisScopeExpressionAudit'][0]['expression']['notEstablished'][0]['quantifier']='exists' if quantifier=='all' else 'all'
    assert not context_for_record(wrong,[current])


def test_different_method_variants_never_share_a_subject_or_swap_values():
    raw=quantified();raw['scopeExpression']['observedSettings']=[
        {'subject':'A','attribute':'平台','value':'GPU X'},
        {'subject':'A*','attribute':'平台','value':'GPU Y'}]
    text=materialize(raw,3)[0]['text']
    assert 'A（平台：GPU X）；A*（平台：GPU Y）' in text
    assert 'A（平台：GPU Y）' not in text


@pytest.mark.parametrize('relation,expected',[
    ('not_entailed','passed'),('entailed','failed'),('undetermined','failed')])
def test_readable_wording_never_replaces_independent_entailment_check(relation,expected):
    from test_deep_research_partitioned_scope_review import checker_for
    raw=quantified();raw['evidenceRefs']=['own'];claim,audit=materialize(raw,3)
    record={'scopeExpressionContractVersion':3,'scopeExpressionReviewContractVersion':3,
        'state':{'synthesisScopeExpressionAudit':[audit]}}
    expression=context_for_record(record,[claim])['c']
    def change(rows,request):rows[0]['relation']=relation
    checker,calls=checker_for(claim,expression,record,
        [{'evidenceId':'own','quote':'Method A was evaluated at pruning rate 66%.'}],modify=change)
    assert checker([claim],[{'evidenceId':'own','quote':'Method A was evaluated at pruning rate 66%.'}])[0]['status']==expected
    assert len(calls)==2 and expression['notEstablished'][0] in calls[-1]['prompt']


@pytest.mark.parametrize('change',[{'text':'已有自由结论'},{'kind':'reported'},
    {'scopeExpression':{'observedSettings':[],'notEstablished':['an implicit universal']}}])
def test_new_display_does_not_repair_conflicting_prose_or_guess_quantification(change):
    raw={**quantified(),**change};before=deepcopy(raw)
    with pytest.raises(ValueError):materialize(raw,3)
    assert raw==before


@pytest.mark.parametrize('version',[3,4])
def test_generation_and_joint_compaction_keep_new_text_and_unchecked_context(version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_scope_compaction import packet
    report,audits,response=packet();initial=deepcopy(report)
    initial['claims'][1].update(text='',scopeExpression=audits[0]['expression'])
    record={'question':'两点，300字以内','scopeExpressionContractVersion':version,'scopeCompactionContractVersion':1,
        'scopeExpressionReviewContractVersion':3,'reportPresentationContractVersion':2,
        'factualReasoningContractVersion':7,'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    prompts=[]
    def invoke(rid,node,prompt,options,**kw):
        prompts.append((node,prompt));return {'content':json.dumps(initial if node=='synthesize' else response)}
    assert 'error_code' not in make_synthesize_node(invoke,update)({'run_id':'r'})
    assert [node for node,_ in prompts]==['synthesize','synthesize_compact']
    body=record['state']['reportBody'];assert body['claims'][1]['text'].startswith('已报告设置：')
    assert record['state']['synthesisScopeExpressionAudit'][0]['verification']=='unchecked'
    assert context_for_record(record,body['claims'])
    assert 'The service groups observations' in prompts[1][1]


@pytest.mark.parametrize('version',[3,4])
def test_new_repair_renders_v3_and_cannot_reuse_v2_request_identity(version):
    from test_deep_research_factual_redraft import inputs
    c,e,checks,requirements=inputs();c['kind']='inference';raw=quantified();raw['evidenceRefs']=['E1']
    states=[];invoke=Mock(return_value={'content':json.dumps([raw])})
    kwargs={'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,
        'requirement_context':requirements,'scope_expression':version}
    out=repair_rejected({'claims':[c]},checks,[e],'解释范围',invoke,json.loads,checkpoint=states.append,**kwargs)
    assert out and out[0]['text'].startswith('已报告设置：')
    assert guidance(version) in invoke.call_args.args[0]
    assert states[-1]['scopeExpressionAudit']['0'][0]['verification']=='unchecked'
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected({'claims':[c]},checks,[e],'解释范围',invoke,json.loads,batch_state=saved,**kwargs)==out
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):
        repair_rejected({'claims':[c]},checks,[e],'解释范围',invoke,json.loads,batch_state=saved,**{**kwargs,'scope_expression':2})
    invoke.assert_not_called()


@pytest.mark.parametrize('version',[3,4])
def test_repair_compaction_uses_new_renderer_and_freezes_its_cache_identity(version):
    from test_deep_research_scope_compaction import packet
    report,audits,response=packet()
    raw={**report['claims'][1],'text':'','scopeExpression':audits[0]['expression']}
    report['claims'][1],audit=materialize(raw,version);states=[]
    invoke=Mock(return_value={'content':json.dumps(response)})
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':[audit]}},'300字以内',invoke,json.loads)
    revised=compact_repairs(*args,presentation_version=2,expression_version=version,checkpoint=states.append)
    assert revised and revised[1]['text'].startswith('已报告设置：')
    assert states[-1]['scopeExpressionAudit'][0]['verification']=='unchecked'
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert compact_repairs(*args,presentation_version=2,expression_version=version,saved=saved)==revised
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):compact_repairs(*args,presentation_version=2,saved=saved)
    invoke.assert_not_called()
