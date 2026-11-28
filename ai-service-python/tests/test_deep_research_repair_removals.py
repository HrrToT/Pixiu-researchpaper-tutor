from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.repair_removals import checked_spans,GUIDANCE
from services.deep_research.verification import verify_claims
from services.deep_research.contracts import DeepResearchError
from test_deep_research_factual_redraft import inputs
from test_deep_research_repair_goals import options


def prepared(version=4):
    c,e,checks,requirements=inputs()
    c.update(text='约束预测差异，从而贴近真实表面。',conditions={})
    return _prepare_repair({'claims':[c]},checks,[e],'解释作用',target_goals=version,claim_check=9,
        **options(requirements)),e


def row(text='约束预测差异。',spans=None):
    return {'claimId':'c','kind':'reported','text':text,'conditions':{},'evidenceRefs':['E1'],
        'detailLevel':'fulltext','discardedDraftSpans':['贴近真实表面'] if spans is None else spans,
        'draftingBasis':{'premiseStatus':'established','observations':[],
            'scopeDecision':'reported_case','unresolved':''}}


def test_declared_removal_is_private_and_never_a_scientific_pass():
    p,e=prepared();before=deepcopy(p);audit=[]
    revised=_parse_repair_response(p,{'content':json.dumps([row()])},json.loads,drafting_audit=audit)
    assert revised[0]['text']=='约束预测差异。'
    assert 'discardedDraftSpans' not in revised[0]
    assert audit[0]['discardedDraftSpans']==['贴近真实表面']
    assert audit[0]['removalVerification']=='edit_consistency_only'
    semantic=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'Still requires original evidence.'}])
    assert not verify_claims(revised,[e],semantic)['accepted'];semantic.assert_called_once()
    assert p==before and GUIDANCE in p['prompt']


@pytest.mark.parametrize('mutation',['missing','string','foreign','duplicate','retained','hedged'])
def test_false_or_malformed_declared_edits_cannot_become_revisions(mutation):
    p,_=prepared();value=row()
    if mutation=='missing':value.pop('discardedDraftSpans')
    if mutation=='string':value['discardedDraftSpans']='贴近真实表面'
    if mutation=='foreign':value['discardedDraftSpans']=['source words not in original']
    if mutation=='duplicate':value['discardedDraftSpans']*=2
    if mutation=='retained':value['text']='约束预测差异，从而贴近真实表面。'
    if mutation=='hedged':value['text']='约束预测差异，从而可能贴近真实表面。'
    assert _parse_repair_response(p,{'content':json.dumps([value])},json.loads)==[]


def test_empty_declaration_is_not_approval_and_supported_inference_remains_available():
    p,_=prepared();assert 'c' in p['reportedInferenceRepairIds']
    value=row('这是依据所引观察作出的有条件判断。',[])
    value['kind']='inference';value['draftingBasis']['scopeDecision']='bounded_inference'
    revised=_parse_repair_response(p,{'content':json.dumps([value])},json.loads)
    assert revised[0]['kind']=='inference' and revised[0]['text']==value['text']
    assert 'verification' not in revised[0]


def test_legacy_goal_three_keeps_previous_wire_and_optional_metadata_behavior():
    p,_=prepared(3);value=row();value.pop('discardedDraftSpans')
    assert 'repairRemovalContractVersion' not in p and GUIDANCE not in p['prompt']
    assert _parse_repair_response(p,{'content':json.dumps([value])},json.loads)


def test_structured_targets_with_no_prose_can_declare_no_removed_prose():
    assert checked_spans({'text':'','discardedDraftSpans':[]},{'text':''})==[]


def test_old_pending_request_cannot_upgrade_to_new_removal_policy_and_resend():
    c,e,checks,requirements=inputs();states=[]
    class Unknown(Exception):pass
    with pytest.raises(Unknown):
        repair_rejected({'claims':[c]},checks,[e],'解释',Mock(side_effect=Unknown()),json.loads,
            target_goals=3,checkpoint=lambda s:states.append(deepcopy(s)),**options(requirements))
    invoke=Mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected({'claims':[c]},checks,[e],'解释',invoke,json.loads,
            target_goals=4,batch_state=states[-1],**options(requirements))
    invoke.assert_not_called()
