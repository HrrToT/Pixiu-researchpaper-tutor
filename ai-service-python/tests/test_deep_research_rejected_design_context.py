from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.deep_research.rejected_design_context import enabled,rejected_context
from services.deep_research.verification import verify_claims
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_verify_node
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.experiment_review_envelope import build
from services.deep_research.design_consistency import enforce_design_consistency
from test_deep_research_canonical_initialization import claims as canonical
from test_deep_research_review_envelope import Capture,target_with_source,args
from test_deep_research_shared_experiment_repair import json_after


def pair():
    bad=canonical()[-1]
    bad['executionSpec'].pop('baselineInitialization')
    bad['reviewContextState']={'status':'approved'}
    good={'claimId':'limits','kind':'proposal','designRole':'limits','designContractVersion':2,
        'text':'Unexecuted fixture limitation; no population inference.', 'evidenceRefs':[]}
    return bad,good


@pytest.mark.parametrize('version',[None,True,False,0,1,8,'2'])
def test_legacy_versions_keep_exact_two_argument_callback_and_no_rejected_context(version):
    bad,good=pair();seen=[]
    def check(rows,evidence):seen.append(deepcopy(rows));return []
    result=verify_claims([bad,good],[],check,review_context_version=version)
    assert seen==[[good]] and not result['accepted'] and len(result['rejected'])==2
    assert not enabled(version)


@pytest.mark.parametrize('version',[2,3,4,5,6])
def test_original_failed_definition_checks_and_status_survive_without_promotion(version):
    bad,good=pair();before=deepcopy([bad,good]);seen=[]
    def check(rows,evidence,*,proposal_context):
        seen.extend(deepcopy(proposal_context))
        return [{'claimId':c['claimId'],'status':'passed'} for c in [*rows,*proposal_context]]
    result=verify_claims([bad,good],[],check,review_context_version=version)
    assert [c['claimId'] for c in result['accepted']]==['limits']
    assert result['rejected'][0]['claimId']==bad['claimId']
    assert len(seen)==1 and seen[0]['executionSpec']==bad['executionSpec']
    state=seen[0].pop('reviewContextState')
    assert state=={'status':'rejected','phase':'precheck','checks':[result['rejected'][0]]}
    expected=deepcopy(bad);expected.pop('reviewContextState');assert seen[0]==expected
    assert [bad,good]==before


def test_facts_ambiguous_ids_unsupported_design_versions_and_current_targets_never_become_context():
    bad,good=pair()
    rows=[{**bad,'claimId':'dupe'},{**bad,'claimId':'dupe'},
        {**bad,'claimId':'fact','kind':'reported'},
        {**bad,'claimId':'old','designContractVersion':True},bad,good,None]
    rejected=[{'claimId':cid,'reason':'fixture'} for cid in ['dupe','fact','old',bad['claimId'],'limits']]
    context=rejected_context(rows,rejected,exclude=['limits'])
    assert [c['claimId'] for c in context]==[bad['claimId']]
    assert context[0]['reviewContextState']['status']=='rejected'
    assert rejected_context(rows,[],exclude=[])==[]


def test_rejected_dependency_cannot_survive_as_an_approved_workflow():
    rows=canonical();bad=next(c for c in rows if c['designRole']=='data')
    bad['executionSpec'].pop('split')
    # Even an over-permissive mock cannot revive a hard rejection or its dependents.
    def check(targets,evidence,*,proposal_context):
        assert [c['claimId'] for c in proposal_context]==[bad['claimId']]
        return [{'claimId':c['claimId'],'status':'passed'} for c in [*targets,*proposal_context]]
    checked=verify_claims(rows,[],check,review_context_version=2)
    result=enforce_design_consistency(checked,protocol_required=2,workflow_required=4)
    assert bad['claimId'] not in {c['claimId'] for c in checked['accepted']}
    assert not any(c['designRole'] in {'steps','controls'} for c in result['accepted'])


@pytest.mark.parametrize('version',[2,3,4,5,6])
def test_rejected_context_cannot_donate_factual_evidence_or_a_verdict_target(version):
    claim,own=target_with_source('target','own',30)
    bad,other=target_with_source('rejected','other',30)
    bad['designRole']='data'
    bad['reviewContextState']={'status':'rejected','phase':'precheck','checks':[{'reason':'invalid_split'}]}
    capture=Capture()
    checker=BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=version)
    checker([claim],[own,other],proposal_context=[bad])
    assert len(capture.sent)==1
    prompt=capture.sent[0]['prompt']
    assert [c['claimId'] for c in json_after(prompt,'Claims:\n')]==['target']
    context=json_after(prompt,'Other proposed statements, for consistency only (not evidence and not verdict targets):\n')
    assert context[0]['reviewContextState']==bad['reviewContextState']
    assert 'evidenceRefs' not in context[0]
    sources=json_after(prompt,'Evidence:\n')['evidence']
    assert len(sources)==1 and next(iter(sources.values()))['quote']==own['quote']
    assert other['quote'] not in prompt and 'Rejected context policy:' in prompt


@pytest.mark.parametrize('version',[2,3,4,5,6])
def test_capacity_splits_preserve_rejected_state_and_full_original_definitions(version):
    a,ea=target_with_source('a','one',2000);b,eb=target_with_source('b','two',2000)
    failed=pair()[0];failed['reviewContextState']={'status':'rejected','phase':'precheck','checks':[{'reason':'missing_state'}]}
    def checker(capture):return BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=version)
    full=Capture();checker(full)._check_batch([a,b],[ea,eb],[failed],node='verify_design_science')
    capture=Capture(len(full.sent[0]['prompt'].encode())-1000)
    checker(capture)._check_batch([a,b],[ea,eb],[failed],node='verify_design_science')
    assert len(capture.sent)==2
    for request in capture.sent:
        context=json_after(request['prompt'],'Other proposed statements, for consistency only (not evidence and not verdict targets):\n')
        row=next(c for c in context if c['claimId']==failed['claimId'])
        assert row['executionSpec']==failed['executionSpec'] and row['reviewContextState']==failed['reviewContextState']
        assert len(request['prompt'].encode())<=capture.limit


def test_facade_and_initial_graph_route_precheck_failures_without_rechecking_them():
    bad,good=pair();record={'experimentReviewEnvelopeContractVersion':2,
        'state':{'reportBody':{'claims':[bad,good]},'evidence':[]}}
    fake=SimpleNamespace(_repo=SimpleNamespace(require_run=lambda _:record))
    seen=[]
    def semantic(rows,evidence,*,proposal_context):
        seen.extend(proposal_context);return []
    def update(_id,change,**_):
        nonlocal record
        record=change(deepcopy(record));return record
    node=make_verify_node(ResearchFacade._get_verify_claims(fake,'r'),semantic,update,llm_invoke=None)
    node({'run_id':'r'})
    assert len(seen)==1 and seen[0]['claimId']==bad['claimId']
    assert record['state']['verifiedReport']['verifiedClaims']==[]
    assert any(c['claimId']==bad['claimId'] for c in record['state']['verifiedReport']['rejectedClaims'])


def test_revision_keeps_unchanged_failed_sibling_but_uses_current_revised_definition():
    bad,good=pair();other={**deepcopy(bad),'claimId':'other'}
    old={**deepcopy(good),'text':'Old rejected limitation.'}
    failures=[{'claimId':c['claimId'],'reason':'needs_revision'} for c in [bad,other,old]]
    record={'experimentReviewEnvelopeContractVersion':2,'state':{
        'reportBody':{'claims':[bad,other,old]},'evidence':[], 'repairAttempted':True,
        'initialVerification':{'accepted':[],'rejected':failures},
        'initialAnswerCoverage':{'status':'not_requested','gaps':[]},
        'repairReport':{'claims':[bad,other,old]},'repairTargets':{'accepted':[],'rejected':failures},
        'repairDraft':[bad,good]}}
    calls=[]
    class Checker:
        def check_revisions(self,targets,evidence,accepted,*,proposal_context):
            calls.append(deepcopy((targets,accepted,proposal_context)));return []
    def update(_id,change,**_):
        nonlocal record
        record=change(deepcopy(record));return record
    fake=SimpleNamespace(_repo=SimpleNamespace(require_run=lambda _:record))
    node=make_verify_node(ResearchFacade._get_verify_claims(fake,'r'),Checker(),update,llm_invoke=Mock())
    node({'run_id':'r'})
    assert len(calls)==1
    targets,accepted,context=calls[0]
    assert targets==[good] and accepted==[]
    assert {c['claimId'] for c in context}=={bad['claimId'],'other'}
    assert {c['reviewContextState']['phase'] for c in context}=={'precheck','initial_verification'}
    assert all(c['claimId']!='limits' for c in context)
    assert not record['state']['verifiedReport']['verifiedClaims']
    previous=deepcopy(calls);node({'run_id':'r'});assert calls==previous


def test_version_one_envelope_stays_literal_and_context_version_two_is_explicit():
    kw=args('analysis');old=build(**kw)
    assert build(**kw,version=1)==old and 'Rejected context policy:' not in old
    assert build(**kw,version=2).startswith(old+'\n\n')
