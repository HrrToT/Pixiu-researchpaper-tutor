"""Actual audit inputs include frozen decisions and their own original evidence."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.execution_workflow_blueprint import bind
from services.deep_research.workflow_representation_review import context, remap_refs
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification_aliases import encode_verification_inputs
from test_deep_research_canonical_initialization import claims
from test_deep_research_workflow_representation_slots import setup as workflow_setup


def setup():
    record, invoke, run = workflow_setup()
    responses = list(invoke.side_effect)
    declaration = json.loads(responses[1]['content'])
    declaration['conventions'].append({'name': 'Renderer convention E1 stays literal',
        'definition': 'Physical coordinates, normalized basis; source literal E1 stays unchanged.',
        'origin': 'paper', 'sourceRefs': ['E2']})
    declaration['sourceRefs'] = ['E1', 'E2']
    responses[1]['content'] = json.dumps(declaration)
    invoke.side_effect = responses
    saved = run()
    cs = claims()
    for claim in cs:
        claim.pop('executionSpec', None)
        claim['designContractVersion'] = 2
        claim['evidenceRefs'] = ['a']
    report, binding = bind({'claims': cs}, saved)
    record['state']['executionWorkflowBinding'] = binding
    evidence = [{'evidenceId': identity, 'quote': quote, 'accessLevel': 'fulltext',
        'sourceTitle': 'Fixture paper', 'sourceWorkId': 'work', 'sourceVersionId': 'v1',
        'location': {'page': 1}, 'sourceContext': 'Original preceding sentence. ' + quote + '. Original following sentence.'}
        for identity, quote in [('a', 'Baseline methods original quote'),
                                ('b', 'Renderer basis and normalization original quote')]]
    return record, report['claims'], evidence


def test_actual_bound_steps_and_declaration_keep_full_unapproved_choices_and_origins():
    record, cs, evidence = setup()
    before = deepcopy((record, cs, evidence))
    view = context(record, [cs[0]], cs[1:])
    assert view['stepsClaimId'] == 'steps' and view['scientificApproval'] is False
    assert view['sharedRepresentation']['sourceRefs'] == ['a', 'b']
    convention = view['sharedRepresentation']['conventions'][-1]
    assert convention['sourceRefs'] == ['b'] and convention['origin'] == 'paper'
    assert 'E1 stays unchanged' in convention['definition']
    assert (record, cs, evidence) == before


@pytest.mark.parametrize('change', ['missing_binding', 'wrong_digest', 'approved', 'missing_steps',
    'step_values', 'step_id', 'step_role', 'raw_response', 'frozen', 'metadata', 'alias', 'pending'])
def test_tampered_or_missing_binding_cannot_reach_a_model(change):
    record, cs, evidence = setup()
    bp = record['state']['executionWorkflowBlueprint']
    if change == 'missing_binding': record['state'].pop('executionWorkflowBinding')
    elif change == 'wrong_digest': record['state']['executionWorkflowBinding']['blueprintDigest'] = 'changed'
    elif change == 'approved': bp['scientificApproval'] = True
    elif change == 'missing_steps': cs.pop()
    elif change == 'step_values': cs[-1]['executionSpec']['baselineMode'] = 'existing'
    elif change == 'step_id': cs[-1]['claimId'] = 'other'
    elif change == 'step_role': cs[-1]['designRole'] = 'controls'
    elif change == 'raw_response': bp['representation']['response']['content'] = '{}'
    elif change == 'frozen': bp['representation']['frozen']['valueDigest'] = 'changed'
    elif change == 'metadata': bp['units']['metadata']['value']['baselineMode'] = 'existing'
    elif change == 'alias': bp['aliases']['E1'] = 'different'
    elif change == 'pending': bp['representation']['status'] = 'pending'
    send = Mock()
    checker = BudgetedSemanticChecker(send, 'fixture',
        workflow_representation_context=lambda claims, ctx: context(record, claims, ctx))
    with pytest.raises(DeepResearchError, match='共享表示'):
        checker._check_batch([cs[0]], evidence, cs[1:])
    send.assert_not_called()


@pytest.mark.parametrize('marker', [None, 0, 1, 2, 3, True, '4'])
def test_legacy_requests_and_nonexperimental_facts_have_no_new_context(marker):
    record, cs, _ = setup()
    if marker is None: record.pop('workflowRepresentationContractVersion')
    else: record['workflowRepresentationContractVersion'] = marker
    assert context(record, cs, []) is None


def test_factual_review_does_not_inherit_experimental_materials():
    record, _, _ = setup()
    assert context(record, [{'claimId': 'fact', 'kind': 'reported'}], []) is None


def test_production_checker_factory_reads_current_durable_binding():
    from services.deep_research.facade import ResearchFacade
    record, cs, _ = setup()
    facade = object.__new__(ResearchFacade)
    facade._repo = Mock()
    facade._repo.require_run.return_value = record
    checker = facade._build_semantic_checker('fixture', Mock())
    assert checker._workflow_representation_context([cs[-1]], cs[:-1])['stepsClaimId'] == 'steps'
    record['state']['executionWorkflowBlueprint']['representation']['status'] = 'pending'
    with pytest.raises(DeepResearchError, match='共享表示'):
        checker._workflow_representation_context([cs[-1]], cs[:-1])


def test_actual_review_prompt_contains_own_quotes_full_context_and_semantic_obligations():
    record, cs, evidence = setup()
    send = Mock(return_value={'content': '{"items":[]}', 'finishReason': 'stop'})
    checker = BudgetedSemanticChecker(send, 'fixture', prospective_review=3, prospective_envelope=10,
        workflow_representation_context=lambda claims, ctx: context(record, claims, ctx))
    with pytest.raises(DeepResearchError, match='未完整返回'):
        checker._check_batch([cs[-1]], evidence, cs[:-1], node='verify_design_config')
    assert send.call_count == 1
    prompt = send.call_args.kwargs['prompt']
    assert 'Renderer basis and normalization original quote' in prompt
    assert 'Original preceding sentence' in prompt and 'Original following sentence' in prompt
    assert 'Exact unapproved shared representation' in prompt
    assert 'transforms/inverses' in prompt and 'actual initializers' in prompt
    assert 'not scientifically accepted' in prompt
    assert 'Physical coordinates, normalized basis; source literal E1 stays unchanged.' in prompt
    assert '"sourceRefs":["E2"]' in prompt
    assert record['state']['executionWorkflowBlueprint']['scientificApproval'] is False


def test_missing_declaration_source_is_rejected_without_silent_evidence_clipping():
    record, cs, evidence = setup()
    send = Mock()
    checker = BudgetedSemanticChecker(send, 'fixture',
        workflow_representation_context=lambda claims, ctx: context(record, claims, ctx))
    with pytest.raises(ValueError, match='Missing bound review evidence'):
        checker._check_batch([cs[-1]], evidence[:1], cs[:-1])
    send.assert_not_called()


def test_full_representation_over_capacity_is_not_sent_or_trimmed():
    record, cs, evidence = setup()
    # The bound quote cannot be omitted just because it exceeds request capacity.
    evidence[-1]['quote'] = 'literal original evidence ' * 2000
    send = Mock()
    checker = BudgetedSemanticChecker(send, 'fixture', prospective_review=3, prospective_envelope=10,
        workflow_representation_context=lambda claims, ctx: context(record, claims, ctx))
    verdicts = checker._check_batch([cs[-1]], evidence, cs[:-1], node='verify_design_config')
    assert verdicts[0]['executionState'] == 'not_started'
    assert verdicts[0]['reviewInputCapacity']['inputBytes'] > 24000
    send.assert_not_called()


def test_additional_evidence_aliasing_preserves_claims_and_does_not_rewrite_literals():
    claims = [{'claimId': 'target', 'evidenceRefs': ['a']}]
    evidence = [{'evidenceId': 'a', 'quote': 'literal E1'}, {'evidenceId': 'b', 'quote': 'literal E2'}]
    original = deepcopy((claims, evidence))
    wire, rows, reverse = encode_verification_inputs(claims, evidence, additional_refs=['b'])
    assert reverse == {'E1': 'a', 'E2': 'b'}
    assert wire[0]['evidenceRefs'] == ['E1'] and rows[1]['quote'] == 'literal E2'
    assert (claims, evidence) == original
    value = {'sourceRefs': ['a'], 'text': 'a and E1', 'encoding': 'a', 'nested': [{'sourceRefs': ['b']}]}
    mapped = remap_refs(value, {'a': 'E1', 'b': 'E2'})
    assert mapped['text'] == value['text'] and mapped['encoding'] == 'a'
    assert mapped['nested'][0]['sourceRefs'] == ['E2']
