from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.answer_point_intent import repair_guidance
from services.deep_research.repair import _prepare_repair,_parse_repair_response
from services.deep_research.verification import verify_claims


def packet(policy):
    first={'claimId':'c1','kind':'reported','text':'作者报告结果。','evidenceRefs':['e1'],'obligationIds':['o']}
    target={'claimId':'c2','kind':'inference','text':'条件尚待核查。','evidenceRefs':['e2'],'obligationIds':['o']}
    ev=[{'evidenceId':eid,'quote':'同篇原始材料。','sourceWorkId':'paper','sourceVersionId':'v1',
         'contentHash':'hash','accessLevel':'fulltext','verification':{'literal':'passed'},'obligationIds':['o']} for eid in ('e1','e2')]
    ev.append({**ev[0],'evidenceId':'foreign','sourceWorkId':'other'})
    report={'claims':[first,target]};checks={'accepted':[first],'rejected':[{'claimId':'c2','reason':'answer_incomplete'}]}
    intents={'c2':{'scopeDecision':'bounded_inference','unresolved':'其他条件'}}
    p=_prepare_repair(report,checks,ev,'核查条件',claim_check=policy,answer_intents=intents)
    return report,checks,ev,intents,p


def test_shared_material_permission_is_distinct_from_borrowed_approval_and_legacy_stays():
    intent={'c':{'scopeDecision':'bounded_inference','unresolved':'未知条件'}};before=deepcopy(intent)
    old=repair_guidance(intent,['c']);new=repair_guidance(intent,['c'],clarify_shared_sources=True)
    assert "move another point's citations" in old and "move another point's citations" not in new
    assert "THIS target's allowed evidence list" in new and 'do not inherit' in new
    assert 'UNTRUSTED, UNVERIFIED' in old and 'UNTRUSTED, UNVERIFIED' in new
    assert intent==before


def test_new_repair_prompt_clarifies_without_expanding_source_permissions():
    report,checks,ev,intents,new=packet(8);*_,old=packet(7)
    assert set(new['allowed']['c2'])=={'e1','e2'} and new['allowed']==old['allowed']
    assert new['originals']==old['originals'] and report['claims'][0]['evidenceRefs']==['e1']
    assert 'even if another point' in new['prompt'] and 'even if another point' not in old['prompt']
    assert 'Condition source index' in new['prompt']
    assert 'foreign' not in new['aliases'].values()


def test_shared_allowed_reference_still_needs_this_targets_own_evidence_and_review():
    report,checks,ev,intents,p=packet(8)
    alias=next(key for key,value in p['aliases'].items() if value=='e1')
    row={'claimId':'c2','kind':'inference','text':'本条依据仍需独立核查。','evidenceRefs':[alias],'conditions':{}}
    out=_parse_repair_response(p,{'content':json.dumps([row])},json.loads)
    assert len(out)==1 and out[0]['evidenceRefs']==['e1'] and report['claims'][1]['evidenceRefs']==['e2']
    checker=Mock(return_value=[{'claimId':'c2','status':'unresolved','reason':'not established for this target'}])
    result=verify_claims(out,ev,checker)
    assert not result['accepted'] and result['rejected'][0]['reason']=='semantic_unresolved'
    checker.assert_called_once()
    row['evidenceRefs']=['foreign']
    assert _parse_repair_response(p,{'content':json.dumps([row])},json.loads)==[]


@pytest.mark.parametrize('value',[None,1,'true'])
def test_guidance_policy_cannot_be_selected_by_truthy_invalid_value(value):
    with pytest.raises(ValueError):repair_guidance({},[],clarify_shared_sources=value)
