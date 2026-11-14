from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.table_bindings import validate_table_bindings
from services.deep_research.verification import precheck_claims,verify_claims
from test_deep_research_table_bindings import fixture


@pytest.mark.parametrize('metric,label',[('Size','大小'),('Mem','内存')])
def test_literal_metric_translation_keeps_exact_cells_and_needs_semantic_verdict(metric,label):
    ev,c=fixture();ev['tableData']['groups'][0][1][1]=metric
    c['tableBindings'][1]['metric']=metric;c['text']=c['text'].replace('Mem',label)
    before=deepcopy((ev,c))
    assert validate_table_bindings(c,[ev])=='table_condition_not_displayed'
    assert validate_table_bindings(c,[ev],translated_metrics=True) is None
    assert precheck_claims([c],[ev],table_references_version=1)['rejected']
    assert not precheck_claims([c],[ev],table_references_version=2)['rejected']
    check=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'not independently established'}])
    out=verify_claims([c],[ev],check,table_references_version=2)
    assert not out['accepted'] and out['rejected'][0]['reason']=='semantic_unresolved'
    check.assert_called_once();assert (ev,c)==before


@pytest.mark.parametrize('mode',['wrong_value','wrong_cell','wrong_method','missing_variant','missing_group','missing_aggregate','unrelated_metric'])
def test_translation_does_not_waive_measurement_or_identity_errors(mode):
    ev,c=fixture();ev['tableData']['groups'][0][1][1]='Size'
    c['tableBindings'][1]['metric']='Size';c['text']=c['text'].replace('Mem','大小')
    if mode=='wrong_value':c['text']=c['text'].replace('734MB','735MB')
    elif mode=='wrong_cell':c['tableBindings'][1]['value']='735MB'
    elif mode=='wrong_method':c['text']=c['text'].replace('Ours*','Baseline*')
    elif mode=='missing_variant':c['text']=c['text'].replace('Ours*','Ours')
    elif mode=='missing_group':c['text']=c['text'].replace('Dataset A','Dataset B')
    elif mode=='missing_aggregate':ev['tableData']['groups'][0][0]='Dataset A / mean'
    elif mode=='unrelated_metric':c['text']=c['text'].replace('大小','速度')
    assert validate_table_bindings(c,[ev],translated_metrics=True) is not None


def test_undeclared_translation_policy_cannot_enable_aliases():
    ev,c=fixture();c['text']=c['text'].replace('Mem','内存')
    for version in (None,True,'2',0,1,5):
        assert precheck_claims([c],[ev],table_references_version=version)['rejected']
    assert not precheck_claims([c],[ev],table_references_version=3)['rejected']
    for bad in (None,1,'true'):
        with pytest.raises(ValueError):validate_table_bindings(c,[ev],translated_metrics=bad)
