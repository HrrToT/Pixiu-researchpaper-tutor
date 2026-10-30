"""Condition audit transport preserves scientific gates and legacy contracts."""
from copy import deepcopy
import json
import pytest
from services.deep_research.comparison_reasoning import audit_prompt,validate_audit,enabled
from services.deep_research.verification_aliases import restore_verdict_evidence
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_comparison_reasoning import inputs,audit,difference


def condition_audit(e,alignment='not_established',rows=None):
    a=audit(e,alignment,rows);a['conditionDifferences']=a.pop('differences');return a


def test_condition_contract_is_explicit_and_retains_methodology_and_legacy_schema():
    assert enabled({'comparisonReasoningContractVersion':4})
    p=audit_prompt({'c':'within_study'},4)
    assert 'conditionDifferences' in p and '"differences"' not in p
    assert 'identities of the methods' in p and 'whole-system comparison' in p
    assert 'Comparison reasoning definitions' in p
    for v in (1,2,3):
        old=audit_prompt({'c':'within_study'},v)
        assert 'conditionDifferences' not in old and '"differences"' in old


@pytest.mark.parametrize('alignment',['established','not_established'])
def test_empty_conditions_can_support_bounded_comparison_but_old_method_list_is_not_silently_deleted(alignment):
    c,e=inputs();a=condition_audit(e,alignment)
    assert not validate_audit(c,{'comparisonAudit':a},e,version=4)
    legacy=audit(e,alignment,[difference(e)])
    assert validate_audit(c,{'comparisonAudit':legacy},e,version=4)==['comparison_premise_not_established']
    a['conditionDifferences']=[difference(e)]
    assert validate_audit(c,{'comparisonAudit':a},e,version=4)==['unknown_alignment_is_not_difference']


def test_demonstrated_conditions_require_both_own_literal_values_and_independent_support():
    c,e=inputs('Device Y');a=condition_audit(e,'different',[difference(e)])
    assert not validate_audit(c,{'comparisonAudit':a},e,version=4)
    bad=deepcopy(a);bad['conditionDifferences'][0]['right']['value']='Device Z'
    assert validate_audit(c,{'comparisonAudit':bad},e,version=4)==['comparison_difference_quote_mismatch']
    bad=deepcopy(a);bad['supportsClaim']=False
    assert validate_audit(c,{'comparisonAudit':bad},e,version=4)==['comparison_premise_not_established']
    c2,e2=inputs();bad=condition_audit(e2,'different',[difference(e2,right_value='Device X')])
    assert validate_audit(c2,{'comparisonAudit':bad},e2,version=4)==['comparison_values_not_different']


def test_checker_restores_new_condition_source_aliases_without_rewriting_values_or_accepting_failed_verdict():
    c,e=inputs('Device Y');sent=[]
    a=condition_audit(e,'different',[difference(e)])
    wire=restore_verdict_evidence({'comparisonAudit':a},{r['evidenceId']:f'E{i+1}' for i,r in enumerate(e)})['comparisonAudit']
    assert wire['conditionDifferences'][0]['right']['evidenceId']=='E2'
    def invoke(**kw):
        sent.append(kw)
        return {'content':json.dumps([{'claimId':'c','status':'passed','reason':'fixture','comparisonAudit':wire}])}
    checker=BudgetedSemanticChecker(invoke,'r',comparison_reasoning=True,comparison_audit_version=4,audit_source_fields=True)
    result=checker([c],e)[0]
    assert result['status']=='passed'
    assert result['comparisonAudit']==a
    assert 'comparisonAudit.conditionDifferences' in sent[0]['prompt']
    assert 'comparisonAudit.differences' not in sent[0]['prompt']
    def failed(**kw):return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'unsupported','comparisonAudit':wire}])}
    assert BudgetedSemanticChecker(failed,'r',comparison_reasoning=True,comparison_audit_version=4)([c],e)[0]['status']=='failed'


def test_legacy_wire_prompts_remain_byte_identical():
    import hashlib
    expected={(1, False): 'b44dddec0e92886362b673ff158d5118e702a5b4d09e7d079669d06b91ad096e', (1, True): 'e939dcf7ffdbe37bd9b5ade48f12fad6dceb596c925a9ec5b623a4665c356966', (2, False): 'e7870d87af17c1015e8d7ae3e71df86ff5dddf9584140c28b0768aed0e77de82', (2, True): '9cd58d967bd2f157a78ed50a77e3e6c5e4007ac04b50fbe4ae0a12263c0be2c8', (3, False): 'eafa82ba3ce361e6c986810623593a3f5faf06f5ca783eeee6bd07af67890041', (3, True): '398bf2026e4235e33cc0ee1900d4df04b9cab58f43c007c96a5f1186ad217845'}
    for (version,single),digest in expected.items():
        assert hashlib.sha256(audit_prompt({"c":"within_study"},version,single_decision=single).encode()).hexdigest()==digest
