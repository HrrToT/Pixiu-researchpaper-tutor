from copy import deepcopy
import json

import pytest

from services.deep_research.review_role_map import build as role_map
from services.deep_research.experiment_review_envelope import build
from services.deep_research.rejection_audit import bind
from test_deep_research_review_envelope import args
from test_deep_research_shared_experiment_repair import json_after


def declarations():
    kw=args('hypothesis')
    return [*json.loads(kw['claims_text']),*kw['context']]


def test_hypothesis_resolves_only_actual_unique_analysis_and_preserves_all_values():
    claims=declarations();before=deepcopy(claims)
    hypothesis=next(c for c in claims if c['designRole']=='hypothesis')
    rows=role_map(claims);row=next(r for r in rows if r['claimId']==hypothesis['claimId'])
    ref=hypothesis['executionSpec']['analysisClaimId']
    analysis=next(c for c in claims if c['claimId']==ref)
    assert row['analysisResolved'] and row['analysisRef']==ref
    for binding in row['effectBindings']:
        assert binding['claimId']==ref and binding['path'][:2]==['executionSpec','effects']
        assert binding['path'][-1] in analysis['executionSpec']['effects']
    assert row['availableMetricIds']==[c['claimId'] for c in claims if c['designRole']=='metrics']
    assert claims==before
    assert 'approved' not in row and 'sourceSupport' not in row


@pytest.mark.parametrize('change',['duplicate','foreign_kind','wrong_role','absent'])
def test_links_do_not_inherit_foreign_or_ambiguous_definitions(change):
    claims=declarations();hypothesis=next(c for c in claims if c['designRole']=='hypothesis')
    ref=hypothesis['executionSpec']['analysisClaimId']
    analysis=next(c for c in claims if c['claimId']==ref)
    if change=='duplicate':claims.append(deepcopy(analysis))
    elif change=='foreign_kind':analysis['kind']='reported'
    elif change=='wrong_role':analysis['designRole']='data'
    else:claims.remove(analysis)
    row=next(r for r in role_map(claims) if r['claimId']==hypothesis['claimId'])
    assert not row['analysisResolved'] and row['effectBindings']==[]


def test_new_review_keeps_sources_question_targets_context_and_audits_exact():
    kw=args('hypothesis');before=deepcopy(kw)
    old,new=build(**kw,version=8),build(**kw,version=9)
    for marker in ['Claims:\n','Original research question (objective, not evidence):\n',
        'Other proposed statements, for consistency only (not evidence and not verdict targets):\n',
        'Entire target-role requirements:\n',
        'Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n']:
        assert json_after(new,marker)==json_after(old,marker)
    assert kw['evidence_marker'] in new and kw==before
    assert json_after(new,'Actual review fields (not evidence or approval):\n')==role_map(declarations())


def test_present_field_cannot_be_missing_and_failed_feedback_cannot_promote_claim():
    claim=json.loads(args('metrics')['claims_text'])[0]
    claim['conditions']={'context':'A100, warmup 1 iteration, repeat 3, synchronized CUDA events'}
    finding={'kind':'missing_field','claimId':claim['claimId'],'path':['conditions','context'],
        'reason':'缺少设备','value':claim['conditions']['context']}
    verdict={'claimId':claim['claimId'],'status':'failed','reason':'缺少设备','findings':[finding]}
    invalid=bind(verdict,[claim])
    assert invalid['status']=='failed' and invalid['executionState']=='received_invalid'
    assert invalid['rejectionAudit']['originalFindings']==[finding]
    finding['kind']='incomplete';finding['reason']='需要明确计时区域边界'
    bound=bind(verdict,[claim])
    assert bound['status']=='failed' and bound['rejectionAudit']['bindingState']=='verified'
    assert not bound['rejectionAudit']['scientificRejectionVerified']
