from copy import deepcopy
import json

from services.deep_research.experimental_reasoning import (
    DESIGN_ROLES, PROSPECTIVE_DESIGN_POLICY, design_requirements,
)
from services.deep_research.graph import make_synthesize_node
from services.deep_research.repair import repair_rejected
from services.deep_research.reporting import render_report


def test_oversized_optional_hint_cannot_block_or_be_cited_by_a_bounded_repair():
    claim = {'claimId': 'c', 'kind': 'reported', 'text': 'Original fact.',
             'evidenceRefs': ['anchor'], 'obligationIds': ['o']}
    base = {'sourceWorkId': 'paper', 'sourceVersionId': 'v1', 'accessLevel': 'fulltext',
            'verification': {'literal': 'passed'}, 'obligationIds': ['o']}
    evidence = [dict(base, evidenceId='anchor', quote='Exact original fact.',
                     sourceContext='Before. Exact original fact. After.'),
                dict(base, evidenceId='huge', quote='Unrelated optional detail. ' * 1500),
                dict(base, evidenceId='useful', quote='The useful missing condition.')]
    verification = {'rejected': [{'claimId': 'c', 'missingEvidenceRefs': ['huge', 'useful']}]}
    original = deepcopy((claim, evidence, verification))
    sent = []
    def invoke(prompt):
        sent.append(prompt)
        rows = json.JSONDecoder().raw_decode(prompt.split('Exact available evidence:\n', 1)[1])[0]
        assert len(prompt.encode()) <= 8000
        assert {row['quote'] for row in rows} == {'Exact original fact.', 'The useful missing condition.'}
        anchor = next(row for row in rows if row['quote'] == 'Exact original fact.')
        assert anchor['sourceContext']['before'] == 'Before. '
        assert anchor['sourceContext']['after'] == ' After.'
        # The model attempts to cite the omitted hint; parsing must still reject it.
        return {'content': json.dumps([{**claim, 'evidenceRefs': ['huge']}])}
    assert repair_rejected({'claims': [claim]}, verification, evidence, 'Question', invoke,
                           json.loads, max_prompt_bytes=8000) == []
    assert len(sent) == 1 and (claim, evidence, verification) == original


def test_scoped_writing_requirements_keep_policy_and_full_verifier_contract():
    complete = design_requirements(['quality'])
    selected = design_requirements(['quality'], roles={'data', 'budget'})
    assert selected.startswith(PROSPECTIVE_DESIGN_POLICY)
    assert DESIGN_ROLES['data'][1] in selected and DESIGN_ROLES['budget'][1] in selected
    assert DESIGN_ROLES['analysis'][1] not in selected
    assert DESIGN_ROLES['analysis'][1] in complete
    assert design_requirements(['quality'], roles=set(DESIGN_ROLES)) == complete


def test_short_experiment_still_requests_all_roles_and_their_own_schemas():
    record = {'question': '设计一个简短实验，250字以内', 'budgetContractVersion': 1,
              'hypothesisContractVersion': 1, 'state': {'outputKind': 'experiment_design', 'evidence': []}}
    sent = []
    def update(_, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(_, node, prompt, *args, **kwargs):
        sent.append(prompt)
        return {'content': '{"claims":[],"sections":[]}'}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    outline = json.JSONDecoder().raw_decode(sent[0].split(
        'REQUIRED OUTPUT OUTLINE (one claim for EACH role, even when several share a section):\n', 1)[1])[0]
    assert {row['designRole'] for row in outline} == set(DESIGN_ROLES)
    assert {row['designRole'] for row in outline if row['requiresExecutionSpec']} == {
        'groups', 'data', 'analysis', 'budget', 'hypothesis'}
    assert 'At most 12 claims' in sent[0]


def test_expanded_gap_list_exposes_every_counted_item_without_changing_audit():
    payload = {'gaps': [{'obligationId': f'o{i}', 'question': f'Missing deliverable {i}.'} for i in range(16)]}
    original = deepcopy(payload)
    text = render_report(payload)
    assert '<summary>还有 16 项未完成</summary>' in text
    for gap in payload['gaps']:
        assert gap['question'] in text
    assert payload == original
