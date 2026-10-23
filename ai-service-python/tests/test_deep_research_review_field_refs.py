from copy import deepcopy
import json

import pytest

from services.deep_research.review_field_refs import bind_refs, catalogue
from services.deep_research.experiment_review_envelope import build
from services.deep_research.rejection_audit import validate
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims
from test_deep_research_review_envelope import args, Capture, json_after


def data(): return json.loads(args('data')['claims_text'])[0]


def verdict(c, **change):
    return {'claimId':c['claimId'],'status':'failed','reason':'Original summary.',
        'findings':[{'kind':'incomplete','claimId':c['claimId'],
            'field':'executionSpec/seeds','reason':'种子已给出，尚需说明其用途。',**change}]}


def test_field_code_resolves_the_exact_original_value_without_copying_it_in_response():
    c=data();v=verdict(c);before=deepcopy((c,v));out=bind_refs(v,[c])
    assert out['status']=='failed' and out['rejectionAudit']['bindingState']=='verified'
    f=out['findings'][0]
    assert f['path']==['executionSpec','seeds'] and f['value']==c['executionSpec']['seeds']
    assert validate(out,[c])==[] and (c,v)==before
    a=out['rejectionAudit']['referenceBinding']
    assert a['originalFindings']==v['findings'] and not a['scientificRejectionVerified']
    c['executionSpec']['seeds']=[42]
    other=bind_refs(v,[c])['rejectionAudit']['referenceBinding']
    assert other['requestContextDigest']!=a['requestContextDigest']
    assert other['expandedFindingsDigest']!=a['expandedFindingsDigest']


@pytest.mark.parametrize('value',[None,[],0,False,''])
def test_present_invalid_values_are_not_absent(value):
    c=data();c['executionSpec']['seeds']=value
    out=bind_refs(verdict(c,kind='missing_field'),[c])
    assert out['status']=='failed' and out['executionState']=='received_invalid'
    assert out['rejectionAudit']['errors']==['finding.0.presence']
    assert bind_refs(verdict(c),[c])['findings'][0]['value']==value


def test_missing_required_key_only_gets_an_absent_binding_not_a_default():
    c=data();del c['executionSpec']['seeds']
    out=bind_refs(verdict(c,kind='missing_field'),[c])
    assert out['rejectionAudit']['bindingState']=='verified' and 'value' not in out['findings'][0]
    assert 'seeds' not in c['executionSpec']
    assert bind_refs(verdict(c),[c])['executionState']=='received_invalid'


@pytest.mark.parametrize('change',[
    {'field':'executionSpec.seeds'},{'field':'executionSpec/seeds/0'},
    {'field':'executionSpec/fake'},{'claimId':'foreign'},
    {'path':['executionSpec','seeds']},{'value':[0]},
    {'kind':'unknown'},{'reason':''},
])
def test_unknown_fields_paths_kinds_and_model_supplied_values_fail_closed(change):
    c=data();out=bind_refs(verdict(c,**change),[c])
    assert out['status']=='failed' and out['executionState']=='received_invalid'


def test_ambiguous_ids_and_prose_only_roles_cannot_get_fake_configuration_fields():
    c=data();v=verdict(c)
    assert c['claimId'] not in catalogue([c,deepcopy(c)])
    assert bind_refs(v,[c,deepcopy(c)])['executionState']=='received_invalid'
    c['designRole']='metrics';assert 'executionSpec/seeds' not in catalogue([c])[c['claimId']]
    assert bind_refs(v,[c])['executionState']=='received_invalid'


@pytest.mark.parametrize('findings',[None,{},[],[None]])
def test_malformed_failures_are_retained_as_unreviewed(findings):
    c=data();v={**verdict(c),'findings':findings};out=bind_refs(v,[c])
    assert out['executionState']=='received_invalid'
    assert out['rejectionAudit']['referenceBinding']['originalFindings']==findings


def test_positive_verdict_still_requires_empty_findings_and_all_independent_audits():
    c=data();v={**verdict(c),'status':'passed'}
    assert bind_refs(v,[c])['executionState']=='received_invalid'
    v['findings']=[];assert bind_refs(v,[c])==v
    class Wire(Capture):
        def __call__(self,**request):
            self.sent.append(request)
            return {'content':json.dumps([v]),'finishReason':'stop'}
    wire=Wire();checker=BudgetedSemanticChecker(wire,'r',prospective_review=3,prospective_envelope=10)
    # No dataAvailability/designAudit was supplied: the pointer format never grants a pass.
    assert checker([c],[])[0]['status']=='failed'


def test_new_policy_keeps_question_sources_claims_context_and_positive_requirements_exact():
    kw=args('hypothesis');old=build(**kw,version=9);new=build(**kw,version=10)
    for marker in ('Claims:\n','Original research question (objective, not evidence):\n',
            'Other proposed statements, for consistency only (not evidence and not verdict targets):\n',
            'Entire target-role requirements:\n','Actual review fields (not evidence or approval):\n',
            'Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n'):
        assert json_after(old,marker)==json_after(new,marker)
    assert kw['evidence_marker'] in new and 'literal code' in new


def test_live_checker_expands_negative_refs_and_preserves_audit_in_verification():
    c={'claimId':'limits','kind':'proposal','designContractVersion':2,'designRole':'limits',
        'text':'仅当前窗口的描述性比较。','evidenceRefs':[]}
    v=verdict(c,field='text')
    class Wire(Capture):
        def __call__(self,**request):
            self.sent.append(request);return {'content':json.dumps([v]),'finishReason':'stop'}
    wire=Wire();checker=BudgetedSemanticChecker(wire,'r',prospective_review=3,prospective_envelope=10)
    out=verify_claims([c],[],checker,review_context_version=10)
    assert not out['accepted']
    audit=out['rejected'][0]['rejectionAudit']
    assert audit['bindingState']=='verified' and audit['referenceBinding']['originalFindings']==v['findings']
