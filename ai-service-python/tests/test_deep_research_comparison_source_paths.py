from copy import deepcopy
import json
import pytest
from services.deep_research.comparison_reasoning import audit_prompt,validate_audit
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_comparison_reasoning import inputs,audit


def path_audit(evidence):
    value=audit(evidence);value['conditionDifferences']=value.pop('differences')
    value['premises']=[{'evidenceId':e['evidenceId'],'path':['quote']} for e in evidence]
    return value


def test_new_comparison_schema_uses_existing_source_paths_legacy_stays_exact():
    targets={'c':'cross_study'};old=audit_prompt(targets,4)
    assert old==audit_prompt(targets,4,source_paths=False)
    new=audit_prompt(targets,4,source_paths=True)
    assert '"path":["quote"]' in new and '"quote":"exact own quotation excerpt"' not in new
    assert 'conditionDifferences' in new and 'supportsClaim' in new


@pytest.mark.parametrize('mutation',['none','foreign','missing_source','metadata','unsupported','condition_value'])
def test_paths_retain_actual_ownership_semantics_and_literal_condition_values(mutation):
    claim,evidence=inputs('Device Y');value=path_audit(evidence)
    if mutation=='foreign':value['premises'][0]['evidenceId']='foreign'
    elif mutation=='missing_source':value['premises'].pop()
    elif mutation=='metadata':value['premises'][0]['path']=['contentHash']
    elif mutation=='unsupported':value['supportsClaim']=False
    elif mutation=='condition_value':
        value['alignment']='different';value['conditionDifferences']=[{'dimension':'hardware',
            'left':{'evidenceId':evidence[0]['evidenceId'],'path':['quote'],'value':'Device X'},
            'right':{'evidenceId':evidence[1]['evidenceId'],'path':['quote'],'value':'Device Z'}}]
    before=deepcopy((claim,evidence,value))
    errors=validate_audit(claim,{'comparisonAudit':value},evidence,source_field_bindings=True,version=4)
    assert bool(errors)==(mutation!='none')
    assert (claim,evidence,value)==before


@pytest.mark.parametrize('status',['passed','failed'])
def test_actual_checker_emits_path_schema_and_preserves_negative_verdict(status):
    claim,evidence=inputs();sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);value=path_audit(evidence)
        value['premises']=[{'evidenceId':f'E{i+1}','path':['quote']} for i in range(2)]
        return {'content':json.dumps([{'claimId':'c','status':status,'reason':'Independent fixture judgement','comparisonAudit':value}])}
    checker=BudgetedSemanticChecker(invoke,'r',comparison_reasoning=True,comparison_audit_version=4,
        audit_source_fields=True,scope_source_paths=True,comparison_source_paths=True)
    result=checker([claim],evidence)
    assert result[0]['status']==status and len(sent)==1
    assert 'not retyped quotations' in sent[0]['prompt']
    assert 'For scopeAudit and comparisonAudit premises/condition sides' in sent[0]['prompt']
    assert '"quote":"exact own quotation excerpt"' not in sent[0]['prompt']


@pytest.mark.parametrize('bad',[1,None,'true'])
def test_comparison_path_policy_is_strict_bool(bad):
    with pytest.raises(ValueError,match='policy'):audit_prompt({'c':'cross_study'},4,source_paths=bad)
