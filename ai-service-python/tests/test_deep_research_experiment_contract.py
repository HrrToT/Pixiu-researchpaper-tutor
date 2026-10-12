import json
from copy import deepcopy

from services.deep_research.experimental_reasoning import DESIGN_ROLES
from services.deep_research.graph import make_publish_node
from services.deep_research.reporting import build_sections
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import verify_claims


def publish(claims):
    record = {'state': {'outputKind': 'experiment_design', 'evidence': [{'evidenceId': 'e'}],
        'verifiedReport': {'verifiedClaims': claims, 'rejectedClaims': [],
            'sections': [{'title': title, 'claimIds': [claims[0]['claimId']]}
                         for title in dict.fromkeys(title for title, _ in DESIGN_ROLES.values())]}}}
    saved = {}
    def update(run, mutate, **kwargs):
        nonlocal record
        record = mutate(record)
        return record
    def save(**kwargs):
        saved.update(kwargs)
        return {'publicationId': 'p'}, True
    make_publish_node(save, update)({'run_id': 'r'})
    return saved


def design_claims():
    return [{'claimId': role, 'kind': 'proposal', 'designRole': role,
             'text': requirement, 'evidenceRefs': [], 'verification': 'proposal'}
            for role, (_, requirement) in DESIGN_ROLES.items()]


def test_all_headings_and_vague_proposal_do_not_prove_complete_experiment():
    result = publish([{'claimId': 'c', 'text': '保持其他条件不变并比较结果。',
                       'kind': 'proposal', 'verification': 'proposal', 'evidenceRefs': []}])
    assert result['outcome'] == 'partial'
    missing = {g.get('designRole') for g in result['payload']['gaps']}
    assert {'budget', 'data', 'analysis', 'steps'} <= missing


def test_verified_roles_organize_report_and_missing_budget_cannot_be_hidden():
    claims = design_claims()
    before = deepcopy(claims)
    result = publish(claims)
    assert result['outcome'] == 'complete'
    assert claims == before
    fixed = next(s for s in result['payload']['sections'] if s['title'] == '固定条件')
    assert set(fixed['claimIds']) == {'controls', 'data', 'budget'}
    result = publish([c for c in claims if c['designRole'] != 'budget'])
    assert result['outcome'] == 'partial'
    assert any(g.get('designRole') == 'budget' for g in result['payload']['gaps'])
    assert '训练与恢复预算' in result['report_text']


def test_joint_design_check_keeps_all_definitions_but_separates_factual_evidence():
    batches = []
    def invoke(**kwargs):
        prompt = kwargs['prompt']
        targets = json.loads(prompt.split('Claims:\n', 1)[1].split('\n\nEvidence:', 1)[0])
        batches.append(targets)
        if any(c.get('designRole') for c in targets):
            assert len(targets) == len(DESIGN_ROLES)
            assert 'UNRELATED_PAPER_QUOTE' not in prompt
            assert 'fulfillment of its entire' in prompt
        return {'content': json.dumps([{'claimId': c['claimId'],
                'status': 'failed' if c.get('designRole') == 'budget' else 'passed',
                'reason': 'recovery budget unspecified' if c.get('designRole') == 'budget' else ''}
                for c in targets])}
    facts = [{'claimId': 'fact', 'kind': 'reported', 'text': 'Quality is measured.', 'evidenceRefs': ['e']}]
    evidence = [{'evidenceId': 'e', 'quote': 'UNRELATED_PAPER_QUOTE Quality is measured.',
                 'verification': {'literal': 'passed'}}]
    claims = [*facts, *design_claims()]
    checked = verify_claims(claims, evidence, BudgetedSemanticChecker(invoke, 'r'))
    assert len(batches) == 2
    assert [c['claimId'] for c in checked['accepted']] == [c['claimId'] for c in claims if c['claimId'] != 'budget']
    result = publish(checked['accepted'])
    assert result['outcome'] == 'partial'
    assert any(g.get('designRole') == 'budget' for g in result['payload']['gaps'])


def test_invalid_design_metadata_is_rejected_not_a_crash_or_completion():
    claims = [{'claimId': str(i), 'kind': 'proposal', 'text': 'Example', 'evidenceRefs': [], 'designRole': role}
              for i, role in enumerate([['budget'], 'invented'])]
    result = verify_claims(claims, [], lambda c, e: [])
    assert [r['reason'] for r in result['rejected']] == ['invalid_design_role'] * 2
    assert build_sections(claims, 'experiment_design')
