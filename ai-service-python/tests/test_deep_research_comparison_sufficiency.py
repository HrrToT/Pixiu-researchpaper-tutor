from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.scope_expression import materialize,review_expression,guidance
from services.deep_research.scope_expression_review import context_for_record
from services.deep_research.tools import BudgetedSemanticChecker


def raw():
    return {'claimId':'c','kind':'inference','text':'','conditions':{},'evidenceRefs':['a','b'],
        'scopeExpression':{'observedSettings':[],'notEstablished':[{'type':'comparison_evidence',
            'subjects':['GOF','PGSR'],'quantity':'模型存储或显存'}]}}


def fixture():
    source=raw();claim,audit=materialize(source,5)
    record={'scopeExpressionContractVersion':5,'scopeExpressionReviewContractVersion':3,
        'state':{'synthesisScopeExpressionAudit':[audit]}}
    evidence=[{'evidenceId':'a','quote':'GOF reports Chamfer distance 0.74 mm.','verification':{'literal':'passed'}},
        {'evidenceId':'b','quote':'PGSR reports Chamfer distance 0.49 mm.','verification':{'literal':'passed'}}]
    return claim,record,evidence


def test_explicit_sufficiency_renders_readable_local_limit_without_an_invented_comparator():
    original=raw();before=deepcopy(original);claim,audit=materialize(original,5)
    assert claim['text']=='当前引用不足以比较GOF与PGSR的模型存储或显存。'
    assert audit['verification']=='unchecked' and original==before
    expression=review_expression(original['scopeExpression'],5)
    assert expression['notEstablished']==['当前所引证据提供了足以比较GOF与PGSR的模型存储或显存的对应数据和必要条件']
    assert '全篇' not in claim['text'] and '无提供' not in claim['text']
    assert context_for_record(fixture()[1],[claim])=={'c':expression}
    for version in (1,2,3,4):
        with pytest.raises(ValueError):materialize(original,version)


@pytest.mark.parametrize('change',[
    {'subjects':['GOF']},{'subjects':['GOF','GOF']},{'subjects':['GOF',' GOF ']},
    {'subjects':['GOF','']},{'quantity':''},{'extra':'paper omission'},{'type':'paper_absence'}])
def test_invalid_identity_or_schema_never_becomes_a_boundary(change):
    source=raw();source['scopeExpression']['notEstablished'][0].update(change)
    with pytest.raises(ValueError):materialize(source,5)


@pytest.mark.parametrize('relation',['not_entailed','entailed','undetermined'])
def test_partitioned_checker_keeps_independent_sufficiency_decision(relation):
    claim,record,evidence=fixture();expression=context_for_record(record,[claim])['c'];sent=[]
    def invoke(**kw):
        sent.append(kw)
        return {'content':json.dumps([{'index':0,'proposition':expression['notEstablished'][0],
            'relation':relation,'quantification':'explicit','isNegation':False,'authorOmission':False,
            'reason':'Fixture independent judgement of data sufficiency, never source absence.',
            'premises':[{'evidenceId':'E1','path':['quote']},{'evidenceId':'E2','path':['quote']}]}])}
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_expression_context=lambda cs:context_for_record(record,cs))
    assert checker([claim],evidence)[0]['status']==('passed' if relation=='not_entailed' else 'failed')
    assert len(sent)==1 and all(e['quote'] in sent[0]['prompt'] for e in evidence)
    assert expression['notEstablished'][0] in sent[0]['prompt']


def test_scope_five_required_repair_survives_and_checkpoint_cannot_switch_protocol():
    from services.deep_research.repair import repair_rejected
    from services.deep_research.contracts import DeepResearchError
    claim,_,evidence=fixture();report={'claims':[claim]};checks={'accepted':[],
        'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    revised=raw();revised['evidenceRefs']=['E1','E2'];invoke=Mock(return_value={'content':json.dumps([revised])});states=[]
    kw={'scope_expression':5,'claim_check':9,'required_scope_ids':['c']}
    out=repair_rejected(report,checks,evidence,'比较存储或显存',invoke,json.loads,checkpoint=states.append,**kw)
    assert out and out[0]['text']==claim['text']
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(report,checks,evidence,'比较存储或显存',invoke,json.loads,batch_state=saved,**kw)==out
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,evidence,'比较存储或显存',invoke,json.loads,batch_state=saved,**{**kw,'scope_expression':4})
    invoke.assert_not_called()


def test_scope_guidance_selects_sufficiency_only_for_new_protocol():
    from services.deep_research.factual_prompt import scope_guidance
    for render in (guidance,scope_guidance):
        assert 'comparison_evidence' in render(5) and 'comparison_evidence' not in render(4)

@pytest.mark.parametrize('change',[None,'subjects','quantity','type'])
def test_compaction_preserves_sufficiency_target_and_requires_fresh_audit(change):
    from services.deep_research.scope_compaction import compact
    claim,audit=materialize(raw(),5)
    fact={'claimId':'f','kind':'reported','text':'已有结果。'*100,'conditions':{},'evidenceRefs':['a']}
    report={'claims':[fact,claim]}
    expression=deepcopy(raw()['scopeExpression'])
    if change=='subjects':expression['notEstablished'][0]['subjects']=['A','B']
    elif change=='quantity':expression['notEstablished'][0]['quantity']='渲染质量'
    elif change=='type':expression['notEstablished'][0]={'quantifier':'all','subject':'GOF','comparator':'PGSR','domain':'场景','predicate':'更快'}
    value={'claims':[{'claimId':'f','text':'已有结果。','conditions':{},'scopeExpression':None},
        {'claimId':'c','text':'','conditions':{},'scopeExpression':expression}]}
    invoke=Mock(return_value={'content':json.dumps(value)})
    out,new=compact(report,[audit],'100字以内',invoke,json.loads,expression_version=5)
    assert invoke.call_count==1 and 'Keep their exact type, subjects and quantity' in invoke.call_args.args[0]
    if change is None:
        assert out and out['claims'][1]['text']==claim['text'] and new[0]['verification']=='unchecked'
    else:assert out is None and new==[audit]
