from copy import deepcopy
import json
import pytest
from services.deep_research.factual_scope import audit_prompt, validate_audit
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_audit_source_fields import source


def test_prompt_changes_only_source_representation_for_new_policy():
    old = audit_prompt(['c'], complete_statement=True)
    new = audit_prompt(['c'], complete_statement=True, source_paths=True)
    assert '"quote":"exact original quote/context excerpt"' in old
    assert '"premises":[{"evidenceId":"own E ID","path":["quote"]}]' in new
    assert 'not retyped quote' in new
    assert 'same method, result and scope' in new
    assert audit_prompt(['c'], complete_statement=True) == old


def test_new_policy_resolves_original_fields_without_reinterpreting_old_bad_quotes():
    c,e,a = source();v = {'scopeAudit':a};before = deepcopy((c,e,v))
    assert validate_audit(c,v,[e],source_field_bindings=True,source_paths=True) == []
    copied = deepcopy(v);copied['scopeAudit']['premises'] = [{'evidenceId':e['evidenceId'],'quote':e['quote']}]
    assert validate_audit(c,copied,[e],source_field_bindings=True) == []
    assert validate_audit(c,copied,[e],source_field_bindings=True,source_paths=True) == ['scope_premises_not_bound']
    copied['scopeAudit']['premises'][0]['quote'] = 'The method ... estimate motion.'
    assert validate_audit(c,copied,[e],source_field_bindings=True) == ['scope_premises_not_bound']
    assert validate_audit(c,copied,[e],source_field_bindings=True,source_paths=True) == ['scope_premises_not_bound']
    assert (c,e,v) == before


@pytest.mark.parametrize('change', ['foreign','metadata','mixed_quote','missing','unsupported','stronger'])
def test_binding_cannot_license_foreign_hidden_or_unsupported_assertions(change):
    c,e,a=source();row=a['premises'][0]
    if change=='foreign':row['evidenceId']='other'
    if change=='metadata':row['path']=['sourceTitle']
    if change=='mixed_quote':row['quote']=e['quote']
    if change=='missing':e.pop('sourceContext',None);row['path']=['sourceContext']
    if change=='unsupported':a['supported']=False
    if change=='stronger':a['claimStrength']='universal'
    assert validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True,source_paths=True)


@pytest.mark.parametrize('representation,accepted', [('path',True),('quote',False),('ellipsis',False)])
def test_real_checker_wire_requests_paths_and_keeps_source_support_checks(representation,accepted):
    c,e,a=source();sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);v=deepcopy(a)
        v['premises']=[{'evidenceId':'E1',**({'path':['quote']} if representation=='path' else
            {'quote':e['quote'] if representation=='quote' else 'The method ... estimate motion.'})}]
        return {'content':json.dumps([{'claimId':'c','status':'passed','reason':'fixture','scopeAudit':v}])}
    checker=BudgetedSemanticChecker(invoke,'r',factual_scope=True,audit_source_fields=True,scope_source_paths=True)
    result=checker([c],[e]);assert (result[0]['status']=='passed') == accepted
    assert len(sent)==1 and 'use ONLY unchanged source-field paths' in sent[0]['prompt']
    assert 'For scopeAudit premises require evidenceId+path only' in sent[0]['prompt']
    assert sent[0]['extra_body']['max_tokens']==4000 and sent[0]['use_reserve'] is True
