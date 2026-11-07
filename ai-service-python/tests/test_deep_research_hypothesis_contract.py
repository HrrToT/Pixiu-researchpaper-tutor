import copy
import json
from unittest.mock import Mock, patch

import pytest

from services.deep_research.hypothesis_contract import stamp_hypothesis_contract, enforce_hypothesis_consistency
from services.deep_research.execution_materialization import materialize_execution_claim, verification_claim_view
from services.deep_research.design_completion import prepare_design_completion
from services.deep_research.graph import make_verify_node, make_publish_node, make_synthesize_node
from services.deep_research.verification import verify_claims


def analysis_spec(mode='descriptive'):
    return {'effects': {'interaction': 'L11-L10-L01+L00'},
            'uncertainty': {'mode': 'descriptive', 'boundary': 'Only paired estimates.'}
            if mode == 'descriptive' else {'mode': 'paired_cluster_bootstrap', 'unit': 'scene',
                'repetitions': 1000, 'confidence': 0.95, 'seed': 7},
            'decision': {'mode': 'descriptive', 'boundary': 'No significance or equivalence verdict.'}
            if mode == 'descriptive' else {'mode': mode}}


def hypothesis_spec(purpose='test_zero', reference='a'):
    return {'statement': 'The interaction effect is zero in the selected setting.',
            'analysisClaimId': reference, 'effectKeys': ['interaction'], 'purpose': purpose}


def claim(identity, role, spec=None, marked=False):
    result = {'claimId': identity, 'kind': 'hypothesis' if role == 'hypothesis' else 'proposal',
              'designRole': role, 'designContractVersion': 2, 'text': 'Prospective ' + role,
              'evidenceRefs': []}
    if spec is not None:
        result['executionSpec'] = spec
    if marked:
        result['hypothesisContractVersion'] = 1
    return result


def test_marked_hypothesis_missing_spec_is_rejected_before_semantics_legacy_is_unchanged():
    legacy = claim('h', 'hypothesis')
    checker = Mock(return_value=[{'claimId': 'h', 'status': 'passed'}])
    assert verify_claims([legacy], [], checker)['accepted']
    original = copy.deepcopy(legacy)
    marked = stamp_hypothesis_contract({'claims': [legacy]})
    checker.reset_mock()
    checked = verify_claims(marked['claims'], [], checker)
    assert checked['accepted'] == [] and checked['rejected'][0]['reason'] == 'incomplete_hypothesis_spec'
    checker.assert_not_called()
    assert legacy == original


def test_conflicting_decision_withholds_both_sides_and_all_hypotheses_depending_on_analysis():
    analysis = claim('a', 'analysis', analysis_spec())
    test = claim('h', 'hypothesis', hypothesis_spec(), True)
    explore = claim('explore', 'hypothesis', hypothesis_spec('explore'), True)
    fact = {'claimId': 'fact', 'kind': 'reported', 'text': 'Independent supported fact.'}
    original = {'accepted': [analysis, test, explore, fact], 'rejected': []}
    before = copy.deepcopy(original)
    checked = enforce_hypothesis_consistency(original)
    assert checked['accepted'] == [fact]
    assert {c['claimId'] for c in checked['rejected']} == {'a', 'h', 'explore'}
    assert original == before
    valid = {'accepted': [claim('a', 'analysis', analysis_spec('interval_excludes_zero')), test], 'rejected': []}
    assert enforce_hypothesis_consistency(valid) == valid


def test_missing_wrong_or_ambiguous_reference_never_chooses_an_arbitrary_analysis():
    hypothesis = claim('h', 'hypothesis', hypothesis_spec('explore'), True)
    fact = {'claimId': 'a', 'kind': 'reported', 'text': 'A paper statement.'}
    analysis = claim('a', 'analysis', analysis_spec())
    for rows in [[], [fact], [analysis, copy.deepcopy(analysis)]]:
        checked = enforce_hypothesis_consistency({'accepted': [*rows, hypothesis], 'rejected': []})
        assert checked['accepted'] == rows
        assert checked['rejected'][0]['claimId'] == 'h'
    malformed = claim('h', 'hypothesis', {'analysisClaimId': []}, True)
    assert enforce_hypothesis_consistency({'accepted': [malformed], 'rejected': []})['accepted'] == []


def test_protocol_is_visible_without_internal_analysis_id_and_keeps_original_prose_for_checking():
    hypothesis = claim('h', 'hypothesis', hypothesis_spec('explore', 'internal-analysis-123'), True)
    hypothesis['text'] = 'We promise statistical significance; this contradicts the typed exploration purpose.'
    rendered = materialize_execution_claim(hypothesis)
    assert rendered['text'].startswith(hypothesis['text'])
    assert 'internal-analysis-123' not in rendered['text']
    assert 'explore' not in rendered['text']
    assert 'The interaction effect is zero' in rendered['text']
    assert verification_claim_view(rendered) == hypothesis
    assert materialize_execution_claim(rendered) == rendered


def test_missing_hypothesis_slot_inherits_server_contract_marker():
    report = stamp_hypothesis_contract({'claims': []})
    evidence = [{'evidenceId': 'e', 'sourceWorkId': 'paper', 'sourceVersionId': 'v1',
                 'accessLevel': 'fulltext', 'obligationIds': ['o'], 'verification': {'literal': 'passed'}}]
    draft, checked = prepare_design_completion(report, {'accepted': [], 'rejected': []}, evidence,
                                               [{'obligations': [{'obligationId': 'o'}]}])
    slot = next(c for c in draft['claims'] if c['designRole'] == 'hypothesis')
    assert slot['hypothesisContractVersion'] == 1
    assert slot['text'] == '' and slot['claimId'] in {c['claimId'] for c in checked['rejected']}


def test_display_does_not_invent_an_interval_or_allow_effect_label_to_inject_markdown_lines():
    from services.deep_research.hypothesis_spec import render_hypothesis_spec, validate_hypothesis_spec
    spec = hypothesis_spec('explore')
    spec['effectKeys'] = ['estimate\n# This is an effect label, not a new heading']
    text = render_hypothesis_spec(spec)
    assert '\\n# This is an effect label' in text
    assert '\n# This is an effect label' not in text
    assert '区间' not in text
    malformed = {**spec, 0: 'unexpected numeric key', 'other': True}
    assert all(isinstance(error, str) for error in validate_hypothesis_spec(malformed))


@pytest.mark.parametrize('repair_compatible', [False, True])
def test_graph_repairs_linked_targets_jointly_and_cannot_merge_an_incompatible_fake_pass(repair_compatible):
    hypothesis, analysis = claim('h', 'hypothesis', hypothesis_spec(), True), claim('a', 'analysis', analysis_spec())
    record = {'question': 'Test the zero-interaction hypothesis.', 'state': {
        'reportBody': {'claims': [hypothesis, analysis]}, 'evidence': []}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def semantic(claims, evidence):
        return [{'claimId': c['claimId'], 'status': 'passed'} for c in claims]
    revised_hypothesis = copy.deepcopy(hypothesis)
    revised_hypothesis.pop('hypothesisContractVersion')
    revised_analysis = claim('a', 'analysis', analysis_spec('interval_excludes_zero')
                             if repair_compatible else analysis_spec())
    calls = []
    def invoke(run, node, prompt, options):
        calls.append(node)
        assert node == 'repair_claims'
        assert {c['claimId'] for c in record['state']['repairTargets']['rejected']} == {'a', 'h'}
        return {'content': json.dumps([revised_hypothesis, revised_analysis])}
    with patch('services.deep_research.final_coverage.audit_final_answer',
               return_value={'status': 'not_checked', 'gaps': []}):
        node = make_verify_node(verify_claims, semantic, update, invoke)
        node({'run_id': 'r'})
        node({'run_id': 'r'})
    assert calls == ['repair_claims']
    accepted = record['state']['verifiedReport']['verifiedClaims']
    assert {c['claimId'] for c in accepted} == ({'h', 'a'} if repair_compatible else set())
    if repair_compatible:
        assert next(c for c in accepted if c['claimId'] == 'h')['hypothesisContractVersion'] == 1


def test_resumed_publish_withholds_conflicting_definitions_and_invalidates_old_coverage():
    hypothesis = dict(claim('h', 'hypothesis', hypothesis_spec(), True), verification='proposal')
    analysis = dict(claim('a', 'analysis', analysis_spec()), verification='proposal')
    record = {'state': {'outputKind': 'experiment_design', 'verifiedReport': {
        'verifiedClaims': [hypothesis, analysis], 'rejectedClaims': [],
        'answerCoverage': {'status': 'checked', 'gaps': []}}}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    publish = Mock(return_value=({'publicationId': 'p'}, True))
    result = make_publish_node(publish, update)({'run_id': 'r'})
    assert result['outcome'] == 'inconclusive'
    assert publish.call_args.kwargs['payload']['claims'] == []
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_design_contract'


@pytest.mark.parametrize('enabled', [False, True])
def test_run_creation_snapshot_controls_hypothesis_contract_after_compaction(enabled):
    hypothesis = claim('h', 'hypothesis', hypothesis_spec())
    hypothesis['hypothesisContractVersion'] = 999
    record = {'question': 'Design an experiment.', 'state': {
        'outputKind': 'experiment_design', 'metricDomains': ['quality'], 'evidence': [], 'plan': []}}
    if enabled:
        record['hypothesisContractVersion'] = 1
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    def invoke(run, node, prompt, options, **kwargs):
        assert node == 'synthesize'
        return {'content': json.dumps({'hypothesisContractVersion': 999, 'claims': [hypothesis]})}
    make_synthesize_node(invoke, update)({'run_id': 'r'})
    report = record['state']['reportBody']
    if enabled:
        assert report['hypothesisContractVersion'] == report['claims'][0]['hypothesisContractVersion'] == 1
    else:
        assert 'hypothesisContractVersion' not in report
        assert 'hypothesisContractVersion' not in report['claims'][0]
        assert report['claims'][0]['text'] == hypothesis['text']
