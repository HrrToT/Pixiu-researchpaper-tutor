from copy import deepcopy
import pytest

from scripts.research_component_checkpoint import seed_verification_state
from services.deep_research.answer_point_intent import from_drafting_audit


def test_seed_keeps_repair_intent_and_exact_sources_but_no_old_approval_or_revision():
    claim={'claimId':'c','kind':'inference','text':'A bounded observation.',
        'evidenceRefs':['e'],'verification':'semantic_passed'}
    state={'reportBody':{'claims':[claim],'sections':[{'title':'判断','claimIds':['c']}]},
        'evidence':[{'evidenceId':'e','quote':'Exact source original.'}],
        'factualDraftingAudit':{'c':{'scopeDecision':'bounded_inference','unresolved':'Other settings not established'}},
        'synthesisScopeExpressionAudit':[{'claimId':'c','renderedText':claim['text']}],
        'verifiedReport':{'verifiedClaims':[claim]},'repairAttempted':True,
        'repairBatchState':{'results':{'0':[claim]}},'repairCompaction':{'status':'completed'},
        'initialVerification':{'accepted':[claim]},'initialAnswerCoverage':{'status':'checked','gaps':[]},
        'publication':{'published':True}}
    before=deepcopy(state);seed=seed_verification_state(state)
    assert from_drafting_audit(seed['factualDraftingAudit'],seed['reportBody']['claims'])=={
        'c':{'scopeDecision':'bounded_inference','unresolved':'Other settings not established'}}
    assert seed['evidence']==state['evidence'] and seed['synthesisScopeExpressionAudit']==state['synthesisScopeExpressionAudit']
    assert 'verification' not in seed['reportBody']['claims'][0]
    assert not set(seed)&{'verifiedReport','repairAttempted','repairBatchState','repairCompaction',
        'initialVerification','initialAnswerCoverage','publication'}
    seed['evidence'][0]['quote']='Mutated QA copy'
    assert state==before


@pytest.mark.parametrize('report',[None,{'claims':None},{'claims':['invalid']},
    {'claims':[{'claimId':'c'},{'claimId':'c'}]},{'claims':[{'claimId':None}]}])
def test_seed_rejects_incomplete_or_ambiguous_saved_generation(report):
    with pytest.raises(ValueError):seed_verification_state({'reportBody':report})
