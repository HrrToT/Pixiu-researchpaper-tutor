from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.comparison_methodology import REFERENCE,REFERENCES
from services.deep_research.comparison_reasoning import audit_prompt
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.repair import repair_rejected
from services.deep_research.graph import make_synthesize_node
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import verify_claims
from test_deep_research_comparison_reasoning import inputs,audit


def test_trusted_definitions_only_change_new_policy_without_benchmark_paper_facts():
    old=audit_prompt({'c':'cross_study'},2);new=audit_prompt({'c':'cross_study'},3)
    assert new==old+'\n'+REFERENCE
    assert 'Comparison reasoning definitions' not in old
    assert 'Unknown alignment is\nnot a demonstrated difference' in new
    assert all(url.startswith('https://') for url in REFERENCES)
    assert 'MLPerf' not in REFERENCE and '3DGS' not in REFERENCE and 'LightGaussian' not in REFERENCE


def test_methodology_cannot_turn_a_negative_or_unbound_semantic_verdict_into_pass():
    c,e=inputs();before=deepcopy((c,e));sent=[]
    def invoke(**kwargs):
        sent.append(kwargs)
        return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'Uncited causal premise'}])}
    checker=BudgetedSemanticChecker(invoke,'r',comparison_reasoning=True,comparison_audit_version=3)
    result=verify_claims([c],e,checker)
    assert not result['accepted'] and 'Uncited causal premise' in result['rejected'][0]['detail']
    assert len(sent)==1 and sent[0]['extra_body']=={'max_tokens':4000,'temperature':0.0}
    assert sent[0]['use_reserve'] is True and REFERENCE in sent[0]['prompt']
    assert before==(c,e)


def test_new_generation_and_repair_receive_the_same_logic_without_new_calls_or_sources():
    c,e=inputs();base={'question':'比较两个实验的测量解释，200字以内',
        'comparisonReasoningContractVersion':3,'state':{'outputKind':'paper_comparison','evidence':e,'plan':[]}}
    record=deepcopy(base);sent=[]
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(record);return record
    def invoke(*args,**kwargs):
        sent.append((args,kwargs));return {'finishReason':'length'}
    make_synthesize_node(invoke,update)({'run_id':'r'})
    assert len(sent)==1 and REFERENCE in sent[0][0][2]
    assert all(ev['quote'] in sent[0][0][2] for ev in e)
    repair_sent=[]
    repair_rejected({'claims':[c]},{'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},e,
        '核对比较',lambda prompt:repair_sent.append(prompt) or {'content':'[]'},json.loads,
        comparison_methodology=True)
    assert len(repair_sent)==1 and REFERENCE in repair_sent[0]
    assert all(ev['quote'] in repair_sent[0] for ev in e)
    assert record['state']['evidence']==base['state']['evidence']


def test_unknown_repair_cannot_be_retargeted_to_new_methodological_instructions():
    c,e=inputs();report={'claims':[c]};checks={'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]};states=[]
    def unknown(_):raise OSError('unknown')
    with pytest.raises(OSError):
        repair_rejected(report,checks,e,'核对',unknown,json.loads,checkpoint=states.append)
    dispatch=Mock()
    with pytest.raises(DeepResearchError,match='不一致'):
        repair_rejected(report,checks,e,'核对',dispatch,json.loads,batch_state=states[-1],comparison_methodology=True)
    dispatch.assert_not_called()
