import json
from copy import deepcopy

from services.deep_research.execution_materialization import materialize_execution_claim
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.verification_aliases import encode_verification_inputs, restore_coverage_evidence


def unpack(prompt, marker):
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]


def test_audit_preserves_conflicting_original_prose_all_typed_choices_and_stored_rendering():
    raw = {'claimId': 'groups', 'kind': 'proposal', 'designRole': 'groups',
           'designContractVersion': 2, 'text': 'Original prose proposes threshold 0.5.',
           'evidenceRefs': [], 'conditions': {'scope': 'unexecuted'},
           'executionSpec': {'factors': [{'name': 'threshold',
               'control': {'action': 'Keep all', 'parameters': []},
               'treatment': {'action': 'Threshold the supplied score', 'parameters': [
                   {'name': 'threshold', 'type': 'number', 'value': 0.3}]}}]}}
    rendered = materialize_execution_claim(raw)
    before = deepcopy(rendered)
    captured = []

    def invoke(run, node, prompt, options, **kwargs):
        captured.append(prompt)
        wire = unpack(prompt, 'Accepted final claims: ')[0]
        assert wire['text'] == raw['text']  # A contradiction must remain visible.
        assert wire['executionSpec'] == raw['executionSpec']
        assert wire['conditions'] == raw['conditions']
        return {'content': '[]'}

    result = audit_final_answer('r', 'Propose a threshold.',
        [{'obligations': [{'obligationId': 'o', 'question': 'Propose a threshold.'}]}],
        [rendered], [], invoke, json.loads)
    assert len(captured) == 1 and result['gaps']
    assert rendered == before and rendered['text'].startswith(raw['text'])
    assert len(rendered['text']) > len(raw['text'])


def test_repeated_question_reference_keeps_frozen_requirements_without_mutation():
    question = 'Design the requested experiment with every necessary condition.' * 15
    criterion = {'criterionId': 'procedure', 'requirement': 'Give all executable steps.', 'responseType': 'procedure'}
    plan = [{'obligations': [{'obligationId': 'o', 'question': question,
        'requestExcerpt': question, 'purpose': 'answer_requirement', 'requiredSources': ['paper-v1'],
        'searchQuery': 'acquisition query', 'completionCriteria': [criterion]}]}]
    claims = [{'claimId': 'c', 'kind': 'proposal', 'text': 'A' * 14000, 'evidenceRefs': ['long-original-id']}]
    evidence = [{'evidenceId': 'long-original-id', 'quote': 'B' * 1200, 'sourceWorkId': 'paper-v1'}]
    before = deepcopy((plan, claims, evidence))
    captured = []

    def invoke(run, node, prompt, options, **kwargs):
        captured.append(prompt)
        assert len(prompt.encode()) <= 24000 and question in prompt
        obligations = unpack(prompt, 'Research and answer obligations (including the original question): ')
        assert obligations[0]['questionRef'] == obligations[0]['requestExcerptRef'] == 'userQuestion'
        assert obligations[0]['requiredSources'] == ['paper-v1']
        assert obligations[0]['completionCriteria'] == [criterion]
        assert 'searchQuery' not in obligations[0]
        assert evidence[0]['quote'] in prompt and claims[0]['text'] in prompt
        return {'content': '[]'}

    audit_final_answer('r', question, plan, claims, evidence, invoke, json.loads)
    assert len(captured) == 1 and (plan, claims, evidence) == before


def test_coverage_alias_restoration_changes_only_source_identity_and_handles_collisions():
    claims = [{'claimId': 'E1', 'evidenceRefs': ['E1']}]
    wire, rows, reverse = encode_verification_inputs(claims, [{'evidenceId': 'E1', 'quote': 'E1 is literal source text.'}])
    alias = rows[0]['evidenceId']
    assert alias != 'E1' and wire[0]['claimId'] == 'E1'
    verdicts = [{'obligationId': 'o', 'bindings': [{'claimId': 'E1', 'excerpt': alias}],
        'aspects': [{'basis': {'kind': 'source', 'evidenceId': alias, 'excerpt': alias}},
                    {'basis': {'kind': 'source_metadata', 'evidenceId': alias, 'value': 'fulltext'}},
                    {'basis': {'kind': 'request', 'excerpt': alias}},
                    {'basis': {'kind': 'source', 'evidenceId': 'unknown'}}]}]
    before = deepcopy(verdicts)
    restored = restore_coverage_evidence(verdicts, reverse)
    assert restored[0]['aspects'][0]['basis'] == {'kind': 'source', 'evidenceId': 'E1', 'excerpt': alias}
    assert restored[0]['aspects'][1]['basis']['evidenceId'] == 'E1'
    assert restored[0]['aspects'][2:] == verdicts[0]['aspects'][2:]
    assert restored[0]['bindings'] == verdicts[0]['bindings'] and verdicts == before
