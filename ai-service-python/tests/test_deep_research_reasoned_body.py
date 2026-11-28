from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.authored_body import decode, guidance, reasoning_enabled, GUIDANCE
from services.deep_research.draft_validation import materialize_claims, verification_inputs
from test_deep_research_authored_body import prose, boundary, evidence
from test_deep_research_synthesis_instructions import record


def reasoning():
    return {**prose('r'), 'kind': 'inference', 'body': {'reasoning': {
        'premise': '此操作改变估计中的初始化影响。',
        'consequence': '仅凭这个局部操作不能推出每种任务的最终效果。'}}}


def test_new_branch_preserves_complete_authored_text_and_permissions_without_acceptance():
    raw = reasoning(); before = deepcopy(raw)
    canonical = decode(raw, reasoning=True)
    assert canonical['text'] == raw['body']['reasoning']['premise'] + '\n' + raw['body']['reasoning']['consequence']
    for key in ('claimId', 'kind', 'evidenceRefs', 'obligationIds', 'detailLevel', 'tableBindings'):
        assert canonical[key] == raw[key]
    assert canonical['conditions'] == {} and canonical['scopeExpression'] is None
    report, scopes, audit = materialize_claims({'claims': [raw]}, 5, authored_body=True, reasoning=True)
    assert scopes == [] and audit['rejected'] == []
    assert audit['reasonedBodies'][0]['verification'] == 'unchecked'
    assert audit['reasonedBodies'][0]['body'] == raw['body']
    assert verification_inputs(report['claims'], audit) == report['claims']
    from services.deep_research.verification import verify_claims
    semantic = Mock(return_value=[{'claimId': 'r', 'status': 'failed', 'reason': 'Unresolved inference'}])
    checked = verify_claims(report['claims'], evidence(), semantic)
    assert checked['accepted'] == []
    assert semantic.call_args.args[0][0]['text'] == canonical['text']
    assert raw == before


@pytest.mark.parametrize('mutation', ['reported', 'proposal', 'empty_premise', 'empty_consequence',
    'non_string', 'extra', 'prose', 'boundary', 'canonical_text'])
def test_reasoned_body_rejects_conflicts_and_incomplete_fields(mutation):
    raw = reasoning()
    if mutation in ('reported', 'proposal'): raw['kind'] = mutation
    elif mutation == 'empty_premise': raw['body']['reasoning']['premise'] = ' '
    elif mutation == 'empty_consequence': raw['body']['reasoning']['consequence'] = ''
    elif mutation == 'non_string': raw['body']['reasoning']['consequence'] = ['hidden text']
    elif mutation == 'extra': raw['body']['reasoning']['extraConclusion'] = 'unchecked'
    elif mutation == 'prose': raw['body']['prose'] = {'text': 'second answer', 'conditions': {}}
    elif mutation == 'boundary': raw['body']['boundary'] = boundary()['body']['boundary']
    else: raw['text'] = 'alternate answer'
    with pytest.raises(ValueError): decode(raw, reasoning=True)
    report, scopes, audit = materialize_claims({'claims': [prose(), raw]}, 5, authored_body=True, reasoning=True)
    assert [c['claimId'] for c in verification_inputs(report['claims'], audit)] == ['f']
    assert audit['rejected'][0]['originalClaim'] == raw


def test_old_mode_does_not_decode_new_branch_and_existing_branches_are_exact():
    with pytest.raises(ValueError): decode(reasoning())
    for raw in (prose(), boundary()):
        assert decode(raw) == decode(raw, reasoning=True)
    old = materialize_claims({'claims': [prose(), boundary()]}, 5, authored_body=True)
    new = materialize_claims({'claims': [prose(), boundary()]}, 5, authored_body=True, reasoning=True)
    assert old == new
    assert new[1][0]['expression'] == boundary()['body']['boundary']


def test_new_branch_requires_frozen_complete_initial_authoring_profile():
    base = {**record(), 'authoredBodyContractVersion': 2, 'draftValidationContractVersion': 1}
    assert reasoning_enabled(base, 'paper_comparison')
    assert 'OR {"reasoning"' in guidance(base, 'paper_comparison')
    for key, value in [('authoredBodyContractVersion', 1), ('authoredBodyContractVersion', True),
                       ('draftValidationContractVersion', 0), ('synthesisInputContractVersion', 0)]:
        r = {**base, key: value}
        assert not reasoning_enabled(r, 'paper_comparison')
        assert guidance(r, 'paper_comparison') == GUIDANCE
    assert not reasoning_enabled(base, 'experiment_design')


@pytest.mark.parametrize('bad', [None, 1, 'true'])
def test_reasoning_policy_is_typed(bad):
    with pytest.raises(ValueError): decode(reasoning(), reasoning=bad)
    with pytest.raises(ValueError): materialize_claims({'claims': []}, 5, authored_body=True, reasoning=bad)


def test_trailing_scope_guidance_distinguishes_local_deductions_without_waiving_comparison_audits():
    from services.deep_research.authored_body import scope_guidance
    old = scope_guidance(5)
    new = scope_guidance(5, local_reasoning=True)
    assert 'For authored evidence boundaries use' in old
    assert 'For evidence-comparison or cross-setting generalization boundaries ONLY' in new
    assert 'Local source-grounded mechanism deductions, including their logical limits, use body.reasoning' in new
    assert 'Other points use body.prose with text/conditions.' not in new
    for rule in ('Max4 settings/2 propositions', 'Own sufficient data or a theorem establishing P makes the boundary fail.',
                 'comparison_evidence', 'receives independent factual/scope/coverage review.'):
        assert rule in old and rule in new
    assert scope_guidance(5, local_reasoning=False) == old
    with pytest.raises(ValueError): scope_guidance(4, local_reasoning=True)
