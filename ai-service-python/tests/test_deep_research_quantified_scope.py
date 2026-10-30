"""Authored quantifiers survive generation, repair and bound review unchanged."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.scope_expression import materialize, guidance
from services.deep_research.scope_expression_review import context_for_record
from test_deep_research_scope_expression import claim


def quantified(quantifier='all'):
    value=claim()
    value['scopeExpression']['notEstablished']=[{
        'quantifier':quantifier,'domain':'未包含在所引实验中的数据集',
        'subject':'方法A','comparator':'原始方法',
        'predicate':'SSIM差值的绝对值不超过0.01'}]
    return value


@pytest.mark.parametrize('quantifier,word',[('all','所有情形'),('exists','至少一种情形')])
def test_quantifier_domain_and_comparison_survive_exact_context_reconstruction(quantifier,word):
    raw=quantified(quantifier);before=deepcopy(raw)
    row,audit=materialize(raw,2)
    assert word in row['text'] and '原始方法' in row['text'] and '0.01' in row['text']
    record={'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,
            'state':{'synthesisScopeExpressionAudit':[audit]}}
    context=context_for_record(record,[row])
    assert context['c']['notEstablished'][0] in row['text']
    assert raw==before and audit['expression']==raw['scopeExpression']
    # No semantic verdict is manufactured by rendering or reconstructing.
    assert audit['verification']=='unchecked'
    altered=deepcopy(record)
    altered['state']['synthesisScopeExpressionAudit'][0]['expression']['notEstablished'][0]['quantifier']='exists' if quantifier=='all' else 'all'
    assert context_for_record(altered,[row])=={}
    assert context_for_record({**record,'scopeExpressionContractVersion':1},[row])=={}


@pytest.mark.parametrize('field,value',[
    ('quantifier',None),('quantifier','usually'),('quantifier',True),
    ('domain',''),('subject',' '),('comparator',None),('predicate',[]),
])
def test_missing_authored_fields_are_rejected_without_guessing(field,value):
    raw=quantified();raw['scopeExpression']['notEstablished'][0][field]=value
    before=deepcopy(raw)
    with pytest.raises(ValueError):materialize(raw,2)
    assert raw==before


def test_legacy_string_never_acquires_an_implicit_all_quantifier():
    old=claim();old['scopeExpression']['notEstablished']=['其他数据集质量接近原始方法']
    before=deepcopy(old);row,audit=materialize(old)
    assert row['text'].endswith('这些引用不足以证明：其他数据集质量接近原始方法。')
    with pytest.raises(ValueError):materialize(old,2)
    with pytest.raises(ValueError):materialize(quantified(),1)
    assert old==before


def test_actual_generation_uses_quantified_schema_and_persists_original_ast():
    from services.deep_research.graph import make_synthesize_node
    raw=quantified('exists');record={'scopeExpressionContractVersion':2,'question':'解释范围',
        'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    invoke=Mock(return_value={'content':json.dumps({'claims':[raw]})})
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert 'error_code' not in result and guidance(2) in invoke.call_args.args[2]
    assert record['state']['reportBody']['claims'][0]==materialize(raw,2)[0]
    assert record['state']['synthesisScopeExpressionAudit'][0]['expression']==raw['scopeExpression']


def test_repair_preserves_version_in_checkpoint_and_never_resends_saved_result():
    from services.deep_research.repair import repair_rejected
    from test_deep_research_factual_redraft import inputs
    from services.deep_research.contracts import DeepResearchError
    c,e,check,requirements=inputs();c['kind']='inference'
    raw=quantified();raw['evidenceRefs']=['E1'];states=[]
    invoke=Mock(return_value={'content':json.dumps([raw])})
    kw=dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,
        requirement_context=requirements,scope_expression=2)
    result=repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,
        checkpoint=lambda s:states.append(deepcopy(s)),**kw)
    assert result[0]['text']==materialize(raw,2)[0]['text']
    assert states[-1]['scopeExpressionAudit']['0'][0]['expression']==raw['scopeExpression']
    assert guidance(2) in invoke.call_args.args[0]
    assert repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,
        batch_state=states[-1],**kw)==result
    with pytest.raises(DeepResearchError):
        repair_rejected({'claims':[c]},check,[e],'解释范围',invoke,json.loads,
            batch_state=states[-1],**{**kw,'scope_expression':True})
    assert invoke.call_count==1


@pytest.mark.parametrize('relation,quantification,expected',[
    ('not_entailed','explicit','passed'),('entailed','explicit','failed'),
    ('undetermined','ambiguous','failed')])
def test_typed_declaration_still_needs_independent_semantic_entailment(relation,quantification,expected):
    from test_deep_research_partitioned_scope_review import checker_for
    raw=quantified();raw['evidenceRefs']=['own']
    row,audit=materialize(raw,2)
    record={'scopeExpressionContractVersion':2,'scopeExpressionReviewContractVersion':2,
            'state':{'synthesisScopeExpressionAudit':[audit]}}
    expression=context_for_record(record,[row])['c']
    def modify(rows,_):
        rows[0].update(relation=relation,quantification=quantification)
    evidence=[{'evidenceId':'own','quote':'Method A was evaluated at pruning rate 66%.'}]
    checker,calls=checker_for(row,expression,record,evidence,modify=modify)
    assert checker([row],evidence)[0]['status']==expected
    assert len(calls)==2 and expression['notEstablished'][0] in calls[-1]['prompt']
