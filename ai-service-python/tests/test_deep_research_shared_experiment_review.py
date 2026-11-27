from copy import deepcopy
import json
from unittest.mock import Mock

import pytest


def test_lifecycle_array_binding_proves_absence_without_approving_a_check():
    from services.deep_research.shared_experiment_review import _binding_findings

    proposal = {'steps': [{'reads': ['split'], 'creates': ['checkpoint'], 'updates': [],
                           'operation': {'action': 'Create checkpoint after registration'}}]}
    check = {'checkId': 'setup', 'status': 'failed', 'planBindings': ['/steps/0/reads'],
             'evidenceBindings': [], 'reason': 'No accepted camera update'}
    verdict = {'checks': [check], 'coherent': False, 'issues': [
        {'reason': 'Missing update', 'planBindings': ['/steps/0/updates']},
    ]}
    target = {'kind': 'initialization', 'pathPrefixes': ['/steps']}
    with pytest.raises(ValueError, match='scalar'):
        _binding_findings(verdict, proposal, {'setup': target}, {}, {}, references=True)
    args = verdict, proposal, {'setup': target}, {}, {}
    assert _binding_findings(*args, references=True, state_arrays=True) == ([], {})
    check['status'] = 'passed'
    assert _binding_findings(*args, references=True, state_arrays=True)[0] == ['missing_target_binding']
    check['planBindings'].append('/steps/0/operation/action')
    assert _binding_findings(*args, references=True, state_arrays=True) == ([], {})
    verdict['issues'][0]['planBindings'] = ['/steps']
    with pytest.raises(ValueError, match='scalar'):
        _binding_findings(*args, references=True, state_arrays=True)

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError, UnknownCallError, digest
from services.deep_research.shared_experiment_generation import prepare as generate
from services.deep_research.shared_experiment_review import targets, prepare, assess, descriptor, NODE, _pointer
from services.deep_research.shared_experiment_result import compile_candidate, validate_candidate
from test_deep_research_shared_experiment_generation import context, response as generation_response
from test_deep_research_shared_experiment_plan import proposal


def ready(value=None):
    r, data, aliases = context()
    def checkpoint(v): r['state']['sharedExperimentGeneration'] = deepcopy(v)
    generate(r,data,aliases,invoke=Mock(return_value=generation_response(value)),checkpoint=checkpoint)
    return r,data,aliases


@pytest.mark.parametrize('packet_version', [1, 2, 3, 4])
def test_scoped_review_stops_before_sending_if_a_later_packet_cannot_fit(monkeypatch, packet_version):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    record[review.SCOPED_PACKET_MARKER] = packet_version
    record['budget'] = {'maxTokens': 100000, 'tokens': 67740}
    batches = [
        {'inputBytes': size, 'request': {'extra': {'max_tokens': 4096}}}
        for size in (14845, 31913, 31746)
    ]
    built = {'inputBytes': 31913, 'hardIssues': [], 'targets': [], 'batches': batches}
    monkeypatch.setattr(review, 'build', lambda *args, **kwargs: built)
    invoke, checkpoint = Mock(), Mock()

    with pytest.raises(BudgetExhaustedError) as caught:
        prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert caught.value.details == {'kind': 'tokens', 'limit': 100000, 'used': 104773}
    saved = checkpoint.call_args.args[0]
    assert saved['status'] == 'not_started_budget'
    assert saved['budgetStop'] == {
        'batchIndex': 1, 'limit': 100000, 'spent': 67740, 'reservation': 37033,
    }
    record['state'][review.review_slot(record)] = saved
    checkpoint.reset_mock()
    with pytest.raises(BudgetExhaustedError):
        prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    invoke.assert_not_called()
    checkpoint.assert_not_called()

    record['budget']['tokens'] = 62967
    assert review._initial_batch_budget_stop(record, built) is None


def test_scoped_review_checks_calls_in_both_pools_before_first_packet(monkeypatch):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    record[review.SCOPED_PACKET_MARKER] = 1
    record['budget'] = {'maxModelCalls': 12, 'modelCalls': 5, 'reservedModelCalls': 5,
                        'maxTokens': 100000, 'tokens': 20000}
    batches = [
        {'inputBytes': size, 'request': {'extra': {'max_tokens': 4096}}}
        for size in (14845, 31913, 31746)
    ]
    built = {'inputBytes': 31913, 'hardIssues': [], 'targets': [], 'batches': batches}
    monkeypatch.setattr(review, 'build', lambda *args, **kwargs: built)
    invoke, checkpoint = Mock(), Mock()

    with pytest.raises(BudgetExhaustedError) as caught:
        prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert caught.value.details == {'kind': 'modelCalls', 'limit': 12, 'used': 13}
    assert checkpoint.call_args.args[0]['status'] == 'not_started_budget'
    invoke.assert_not_called()

    record['budget']['maxModelCalls'] = 13
    assert review._initial_batch_budget_stop(record, built) is None


@pytest.mark.parametrize('change', [None, 'design_issue', 'fact_issue', 'fact', 'context', 'response', 'evidence_scope'])
def test_revision_reuses_only_the_original_checked_fact_packet(monkeypatch, change):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    original = record['state']['sharedExperimentGeneration']
    bound = deepcopy(original['boundProposal'])
    binding = original['bindingDigest']
    expected = [target for target in targets(record) if target['kind'] == 'source_fact']
    ids = [target['checkId'] for target in expected]
    assert ids == ['fact_0']
    response = reply({'checks': [{'checkId': ids[0], 'status': 'passed',
        'planBindings': ['/sourceFacts/0/text'], 'evidenceBindings': [{'evidenceId': 'E1', 'field': 'quote'}],
        'reason': 'Checked against the cited source.'}], 'coherent': True, 'issues': []})
    if change in ('design_issue', 'fact_issue'):
        content = json.loads(response['content'])
        content.update(coherent=False, issues=[{'reason': 'Prior issue', 'planBindings': [
            '/data/trainingSplit' if change == 'design_issue' else '/sourceFacts/0/text']}])
        response = reply(content)
    prior_batch = {'checkIds': ids, 'suppliedEvidenceAliases': ['E1']}
    original_responses = [response]
    record['state'].update(sharedExperimentRevision={}, sharedExperimentReview={
        'status': 'checked', 'generationBindingDigest': binding, 'batches': [prior_batch],
        'response': original_responses, 'responseDigest': digest(original_responses),
        'assessment': {'valid': True, 'generationBindingDigest': binding,
                       'reviewDigest': digest({'generation': binding, 'response': original_responses})},
    })
    record[review.SCOPED_PACKET_MARKER] = 3
    record[review.REFERENCE_MARKER] = 3
    record[review.COMPACT_REVIEW_MARKER] = 2
    monkeypatch.setattr(review, '_generation', lambda _: original)
    current = deepcopy(prior_batch)
    if change == 'fact':
        bound['proposal']['sourceFacts'][0]['text'] += ' A new detail.'
    elif change == 'context':
        bound['contextDigest'] = 'changed'
    elif change == 'response':
        response['content'] += ' '
    elif change == 'evidence_scope':
        current['suppliedEvidenceAliases'] = []
    replayed = review._reviewed_fact_batch(record, [current], bound, data, aliases)
    if change in (None, 'design_issue'):
        assert replayed['reusedFactSourceDigest'] == digest(response)
        assert json.loads(replayed['reusedFactBatch']['content']) == {
            'checks': json.loads(response['content'])['checks'], 'coherent': True, 'issues': []}
    else:
        assert replayed == {}


def test_revision_budget_counts_only_pending_packets():
    from services.deep_research import shared_experiment_review as review

    record = {review.SCOPED_PACKET_MARKER: 3, 'budget': {
        'maxModelCalls': 18, 'modelCalls': 12, 'reservedModelCalls': 4,
        'maxTokens': 100000, 'tokens': 70000}}
    batches = [{'inputBytes': size, 'request': {'extra': {'max_tokens': 4096}}}
               for size in (26000, 15000, 16000)]
    assert review._initial_batch_budget_stop(record, {'batches': batches})['reservation'] == 3
    assert review._initial_batch_budget_stop(record, {'batches': batches, 'reusedFactBatch': {}}) is None


def test_revision_review_sends_only_open_packets_and_reloads_same_response(monkeypatch):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    record[review.SCOPED_PACKET_MARKER] = 3
    reused, design = reply({'check': 'fact fixture'}), reply({'check': 'design fixture'})
    batches = [{'inputBytes': 100, 'checkIds': [check], 'request': {'prompt': prompt, 'extra': {'max_tokens': 100}}}
               for check, prompt in [('fact_0', 'reused'), ('section_0', 'design')]]
    built = {'request': batches[0]['request'], 'inputBytes': 100, 'hardIssues': [],
             'targets': [], 'batches': batches, 'reusedFactBatch': reused}
    monkeypatch.setattr(review, 'build', lambda *args, **kwargs: built)
    assessment = Mock(return_value={'valid': True, 'complete': False, 'scientificApproval': False})
    monkeypatch.setattr(review, 'assess', assessment)
    invoke = Mock(return_value=design)

    def checkpoint(saved):
        record['state'][review.review_slot(record)] = deepcopy(saved)

    settled = prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert invoke.call_count == 1 and invoke.call_args.args[:2] == (NODE, 'design')
    assert settled['response'] == [reused, design]
    assert assessment.call_args.args[-1] == [reused, design]
    assert prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint) == settled
    assert invoke.call_count == 1


@pytest.mark.parametrize(('check_key', 'instruction'), [
    ('factChecks', '[checkId,factId,textPointer,optionalContextHints]'),
    ('sectionChecks', '[checkId,criterion,planPathPrefixes]'),
    ('humanChecks', '[checkId,obligationId,criterionId]'),
])
def test_scoped_packet_policy_explains_its_check_shape(check_key, instruction):
    from services.deep_research import shared_experiment_review as review

    packet = {key: [] for key in review.SCOPED_PACKET_CHECKS}
    packet[check_key] = [['example']]
    policy = review._scoped_packet_policy({review.SCOPED_PACKET_MARKER: 2}, packet)
    assert instruction in policy and policy.endswith('\nInput:\n')
    assert 'zero-based indices' in policy
    assert review._scoped_packet_policy({review.SCOPED_PACKET_MARKER: 1}, packet) == review.SCOPED_PACKET_INSTRUCTIONS


def verdict(r, data):
    p = r['state']['sharedExperimentGeneration']['boundProposal']['proposal']
    paths = {'attribution':'/sourceFacts/0/text', 'data':'/data/trainingSplit',
             'initialization':'/states/1/representation', 'interventions':'/factors/0/onOperation/action',
             'pairing_timeline':'/pairing/identityChecks', 'budgets':'/budgets/0/stopRule',
             'measurement':'/metrics/0/procedure', 'analysis':'/analysis/decisionRule',
             'human_requirement':'/hypothesis'}
    checks = []
    for target in targets(r):
        path = target['pathPrefixes'][0] if target['kind']=='source_fact' else paths[target['kind']]
        text = _pointer(p,path)
        checks.append({'checkId':target['checkId'],'status':'passed',
            'planBindings':[{'path':path,'text':text}],
            'evidenceBindings':[{'evidenceId':'E1','field':'quote','text':data['evidence'][0]['quote']}]
                if target['kind'] in ('source_fact','attribution') else [], 'reason':'人工接口夹具，不能计入真实科学验收。'})
    return {'checks':checks,'coherent':True,'issues':[]}


def reply(v): return {'content':json.dumps(v,ensure_ascii=False),'finishReason':'stop'}


def test_resource_review_window_keeps_frozen_premises_and_bound_feedback_evidence():
    from services.deep_research.shared_experiment_review_input import fit_accounted_evidence

    aliases = {'E1':'a', 'E2':'b', 'E3':'c', 'E4':'d'}
    allocation = {'requiredEvidenceIds':['b'], 'suppliedEvidenceIds':list(aliases.values()),
                  'allFrozenPremiseBundlesRetained':True}
    record = {'state':{'sharedExperimentMaterialAllocation':allocation}}
    data = {'evidence':[{'evidenceId':alias,'tableDataRef':alias} for alias in aliases],
            'tables':{alias:{'id':alias} for alias in aliases}, 'question':'Frozen request'}
    proposal = {'sourceFacts':[{'evidenceRefs':['E3']}], 'steps':[{'id':'original'}]}
    def measure(view):
        return view, len(view['evidence'])*10

    view, size, supplied = fit_accounted_evidence(record, data, aliases, proposal, measure, 30, feedback_refs=['E4'])
    assert supplied == ['E2','E3','E4'] and size == 30
    assert set(view['tables']) == set(supplied) and view['question'] == 'Frozen request'
    assert len(data['evidence']) == 4
    _, size, supplied = fit_accounted_evidence(record, data, aliases, proposal, measure, 20, feedback_refs=['E4'])
    assert supplied == ['E2','E3','E4'] and size == 30  # Explicit capacity rejection preserves all required evidence.
    allocation['allFrozenPremiseBundlesRetained'] = False
    _, size, supplied = fit_accounted_evidence(record, data, aliases, proposal, measure, 30)
    assert supplied == list(aliases) and size == 40


def test_partition_covers_each_check_with_original_support_and_keeps_full_proposal():
    from services.deep_research.shared_experiment_review_input import partition_review

    aliases = {'E1': 'a', 'E2': 'b', 'E3': 'c', 'E4': 'd'}
    allocation = {'requiredEvidenceIds': ['d'], 'suppliedEvidenceIds': list(aliases.values()),
                  'allFrozenPremiseBundlesRetained': True}
    record = {'state': {'sharedExperimentMaterialAllocation': allocation}}
    proposal = {'sourceFacts': [{'evidenceRefs': ['E1', 'E2']}], 'steps': [{'id': 'step'}]}
    data = {
        'question': 'Frozen request', 'proposal': proposal, 'requirements': [{'obligationId': 'o'}],
        'evidence': [{'evidenceId': alias, 'tableDataRef': alias} for alias in aliases],
        'tables': {alias: {'id': alias} for alias in aliases},
        'factChecks': [['fact', 'F']], 'sectionChecks': [['section', 'criterion', ['/steps']]],
        'humanChecks': [['user', 'o', 'whole']],
    }
    def measure(view):
        return view, len(view['evidence']) * 10

    facts, plan = partition_review(record, data, aliases, proposal, measure, 20)
    assert facts['checkIds'] == ['fact'] and facts['suppliedEvidenceAliases'] == ['E1', 'E2']
    assert plan['checkIds'] == ['section', 'user'] and 'E4' in plan['suppliedEvidenceAliases']
    assert all(part['request']['proposal'] == proposal and part['inputBytes'] <= 20 for part in (facts, plan))
    assert all(set(part['request']['tables']) == set(part['suppliedEvidenceAliases']) for part in (facts, plan))
    assert plan['request']['requirements'] == data['requirements']
    assert partition_review(record, data, aliases, proposal, measure, 10) == []


def test_output_bounded_review_partitions_even_when_input_fits():
    from services.deep_research.shared_experiment_review_input import partition_bounded_review

    aliases = {'E1': 'a', 'E2': 'b'}
    record = {'state': {'sharedExperimentMaterialAllocation': {
        'requiredEvidenceIds': ['b'], 'suppliedEvidenceIds': list(aliases.values()),
        'allFrozenPremiseBundlesRetained': True}}}
    proposal = {'sourceFacts': [{'id': 'F1', 'evidenceRefs': ['E1']}],
                'steps': [{'id': 'step'}]}
    data = {'proposal': proposal, 'requirements': [{'obligationId': 'o'}],
            'evidence': [{'evidenceId': alias} for alias in aliases], 'tables': {},
            'factChecks': [['fact', 'F1']], 'sectionChecks': [['section', 'criterion', ['/steps']]],
            'humanChecks': [[f'user_{i}', 'o', f'criterion_{i}'] for i in range(5)]}
    def measure(view):
        return view, len(view['evidence']) * 10

    parts = partition_bounded_review(record, data, aliases, proposal, measure, 24, 3)
    assert [part['checkIds'] for part in parts] == [
        ['fact'], ['section'], ['user_0', 'user_1', 'user_2'], ['user_3', 'user_4']]
    assert parts[0]['suppliedEvidenceAliases'] == ['E1']
    assert all(part['request']['proposal'] == proposal for part in parts)
    scoped = partition_bounded_review(record, data, aliases, proposal, measure, 24, 3, scoped=True)
    assert [part['checkIds'] for part in scoped] == [part['checkIds'] for part in parts]
    assert scoped[0]['request']['proposal'] == {'sourceFacts': proposal['sourceFacts']}
    assert scoped[1]['request']['requirements'] == []
    assert all(part['request']['proposal'] == proposal for part in scoped[1:])
    assert all(part['suppliedEvidenceAliases'] == ['E1', 'E2'] for part in parts[1:])
    assert all(part['request']['requirements'] == data['requirements'] for part in parts[1:])

    def measured_with_checks(view):
        return view, len(view['evidence']) * 10 + len(view['humanChecks']) * 3

    assert partition_bounded_review(record, data, aliases, proposal, measured_with_checks, 26, 3) == []
    adaptive = partition_bounded_review(record, data, aliases, proposal, measured_with_checks, 26, 3,
                                       scoped=True, fit_check_count=True)
    assert [part['checkIds'] for part in adaptive] == [
        ['fact'], ['section'], ['user_0', 'user_1'], ['user_2', 'user_3'], ['user_4']]
    assert all(part['request']['proposal'] == proposal and part['suppliedEvidenceAliases'] == ['E1', 'E2']
               for part in adaptive[1:])
    assert all(part['inputBytes'] <= 26 for part in adaptive)
    assert partition_bounded_review(record, data, aliases, proposal, measured_with_checks, 22, 3,
                                   scoped=True, fit_check_count=True) == []


def test_revised_design_packets_can_omit_optional_evidence_without_losing_scope():
    from services.deep_research.shared_experiment_review_input import partition_bounded_review

    aliases = {'E1': 'citation', 'E2': 'frozen_premise', 'E3': 'background'}
    allocation = {'requiredEvidenceIds': ['frozen_premise'], 'suppliedEvidenceIds': list(aliases.values()),
                  'allFrozenPremiseBundlesRetained': True}
    record = {'state': {'sharedExperimentMaterialAllocation': allocation}}
    proposal = {'sourceFacts': [{'id': 'F1', 'evidenceRefs': ['E1']}],
                'steps': [{'id': 'fit', 'action': 'Keep the training split fixed.'}]}
    criterion = {'criterionId': 'criterion', 'requirement': 'Define the split.'}
    data = {'proposal': proposal, 'requirements': [{'obligationId': 'o', 'completionCriteria': [criterion]}],
            'evidence': [{'evidenceId': alias, 'tableDataRef': alias} for alias in aliases],
            'tables': {alias: {'source': alias} for alias in aliases},
            'factChecks': [['fact', 'F1']], 'sectionChecks': [['section', 'criterion', ['/steps']]],
            'humanChecks': [['human', 'o', 'criterion']]}

    def measure(view):
        return view, len(view['evidence']) * 10

    def build(policy):
        return partition_bounded_review(record, data, aliases, proposal, measure, 40, 3, scoped=True,
                                        required_design_evidence_only=policy)

    complete = build(False)
    reduced = build(True)
    assert reduced[0] == complete[0]
    for old, new in zip(complete[1:], reduced[1:], strict=True):
        assert new['checkIds'] == old['checkIds']
        assert new['request']['proposal'] == proposal
        assert new['request']['requirements'] == old['request']['requirements']
        assert new['suppliedEvidenceAliases'] == ['E1', 'E2']
        assert new['request']['evidence'] == data['evidence'][:2]
        assert set(new['request']['tables']) == {'E1', 'E2'}

    allocation['allFrozenPremiseBundlesRetained'] = False
    assert build(True) == complete


def test_numeric_source_context_requires_contiguous_frozen_fulltext():
    from services.deep_research.shared_experiment_review import _visible_numeric_context
    from services.deep_research.verification import precheck_claims

    before = 'The benchmark uses 13 scenes. '
    quote = 'The sensors recorded RGB images.'
    row = {'evidenceId': 'original', 'quote': quote, 'sourceContext': before + quote,
           'accessLevel': 'fulltext', 'verification': {'literal': 'passed'}}
    source = {'evidenceId': 'E1', 'quote': quote, 'accessLevel': 'fulltext',
              'sourceContext': {'before': before, 'after': ''}}
    claim = {'claimId': 'fact', 'kind': 'reported', 'text': 'The benchmark uses 13 scenes.',
             'evidenceRefs': ['original'], 'detailLevel': 'fulltext'}
    context = _visible_numeric_context({'evidence': [source]}, {'original': row}, {'E1': 'original'})
    assert precheck_claims([claim], [row])['rejected'][0]['reason'] == 'numeric_mismatch'
    assert precheck_claims([claim], [row], numeric_context={'original': list(context['original'].values())})['candidates']
    source['sourceContext']['before'] = 'Unrelated 13.'
    assert _visible_numeric_context({'evidence': [source]}, {'original': row}, {'E1': 'original'}) == {}


def test_gaussian_replacement_count_uses_only_explicit_cited_context():
    from services.deep_research.verification import precheck_claims

    passage = 'We replace such Gaussians\nby two new ones, and divide their scale by a factor of 1.6.'
    row = {'evidenceId':'source','quote':'Positions are sampled from the original Gaussian.',
           'accessLevel':'fulltext','verification':{'literal':'passed'}}
    claim = {'claimId':'fact','kind':'reported','text':'论文用2个新高斯替换原高斯，尺度除以1.6。',
             'evidenceRefs':['source'],'detailLevel':'fulltext'}
    options = {'numeric_context': {'source': [passage]}}
    assert precheck_claims([claim], [row], quantity_spelling_version=17, **options)['rejected']
    assert precheck_claims([claim], [row], quantity_spelling_version=18, **options)['candidates']
    assert precheck_claims([claim], [row], quantity_spelling_version=18)['rejected']
    for text in ('We replace such Gaussians by three new ones, with a scale factor of 1.6.',
                 'We inspect Gaussians and two new ones, with a scale factor of 1.6.'):
        assert precheck_claims([claim], [row], quantity_spelling_version=18,
                               numeric_context={'source': [text]})['rejected']


def test_context_hints_point_only_to_the_verified_field_owning_the_figure_number():
    from services.deep_research import shared_experiment_review as review
    from services.deep_research.selection import surrounding_context

    record, data, aliases = ready()
    record[review.FACT_CONTEXT_MARKER] = 3
    fact = record['state']['sharedExperimentGeneration']['boundProposal']['proposal']['sourceFacts'][0]
    local = record['state']['evidence'][0]
    visible = data['evidence'][0]
    local['sourceContext'] = 'Figure 5. ' + local['quote']
    visible['sourceContext'] = surrounding_context(local)
    assert review._fact_context_hints(record, aliases, data, [fact]) == {}

    # The bound proposal is immutable in production. Rebuild the test fixture
    # with a claim carrying the figure number before checking the hint.
    altered = proposal()
    altered['sourceFacts'][0]['text'] = 'Figure 5 reports the public source statement.'
    record, data, aliases = ready(altered)
    record[review.FACT_CONTEXT_MARKER] = 3
    local = record['state']['evidence'][0]
    local['sourceContext'] = 'Figure 5. ' + local['quote']
    data['evidence'][0]['sourceContext'] = surrounding_context(local)
    assert review._fact_context_hints(record, aliases, data, altered['sourceFacts']) == {
        'F1': [{'evidenceId':'E1','field':'before'}]}
    data['evidence'][0]['sourceContext']['before'] = 'Unverified Figure 5.'
    assert review._fact_context_hints(record, aliases, data, altered['sourceFacts']) == {}


def check(r,data,aliases,v=None):
    sent = Mock(return_value=reply(verdict(r,data) if v is None else v))
    states = []
    def checkpoint(value):
        r['state']['sharedExperimentReview'] = deepcopy(value); states.append(deepcopy(value))
    result = prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    return result,sent,states,checkpoint


def test_complete_review_covers_every_fact_section_and_frozen_criterion_then_reuses_receipt():
    r,data,aliases = ready(); before=deepcopy(r['state']['sharedExperimentGeneration'])
    result,sent,states,checkpoint = check(r,data,aliases)
    assert [s['status'] for s in states] == ['pending','response_received','checked']
    assert result['assessment']['valid'] and result['assessment']['complete']
    assert len(result['assessment']['verdict']['checks']) == len(targets(r))
    assert prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint) == result
    assert sent.call_count == 1 and r['state']['sharedExperimentGeneration'] == before
    assert not r['state'].get('reportBody') and not r.get('publication')


@pytest.mark.parametrize('fault', [None, 'object_pointer', 'unknown_pointer', 'foreign_source',
                                 'empty_context', 'wrong_section', 'missing_check'])
def test_review_references_resolve_only_owned_scalar_fields(fault):
    from services.deep_research.shared_experiment_review import REFERENCE_MARKER

    record, data, aliases = ready()
    record[REFERENCE_MARKER] = 1
    body = verdict(record, data)
    for row in body['checks']:
        row['planBindings'] = [binding['path'] for binding in row['planBindings']]
        row['evidenceBindings'] = [{k: v for k, v in binding.items() if k != 'text'}
                                   for binding in row['evidenceBindings']]
    first = body['checks'][0]
    if fault == 'object_pointer':
        first['planBindings'] = ['/data']
    elif fault == 'unknown_pointer':
        first['planBindings'] = ['/missing']
    elif fault == 'foreign_source':
        first['evidenceBindings'][0]['evidenceId'] = 'E2'
    elif fault == 'empty_context':
        first['evidenceBindings'][0]['field'] = 'before'
    elif fault == 'wrong_section':
        first['planBindings'] = ['/hypothesis']
    elif fault == 'missing_check':
        body['checks'].pop()
    result = assess(record, data, aliases, reply(body))
    assert result['valid'] is (fault is None)
    if fault is None:
        assert result['verdict'] == body and result['complete']
        record.pop(REFERENCE_MARKER)
        assert not assess(record, data, aliases, reply(body))['valid']


def test_truncated_review_batch_stops_later_sends_and_restores_from_checkpoint(monkeypatch):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    record[review.COMPACT_REVIEW_MARKER] = 2
    record[review.STOP_INVALID_BATCH_MARKER] = 1
    checks = verdict(record, data)['checks'][:3]
    batches = [{'checkIds': [check['checkId']], 'request': {'prompt': f'batch {i}', 'extra': {}}}
               for i, check in enumerate(checks)]
    monkeypatch.setattr(review, 'build', lambda *args, **kwargs: {
        'batches': batches, 'inputBytes': 100, 'hardIssues': [], 'targets': targets(record),
        review.STOP_INVALID_BATCH_MARKER: 1})
    first = reply({'checks': [checks[0]], 'coherent': True, 'issues': []})
    truncated = {'content': '', 'finishReason': 'length'}
    invoke = Mock(side_effect=[first, truncated])
    checkpoints = []
    def checkpoint(value):
        record['state']['sharedExperimentReview'] = deepcopy(value)
        checkpoints.append(deepcopy(value))

    result = prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert invoke.call_count == 2
    assert result['batchResponses'] == [first, truncated]
    assert result['stoppedAfterInvalidBatch'] == 1
    assert result['status'] == 'invalid_response' and not result['assessment']['scientificApproval']
    record['state']['sharedExperimentReview'] = next(
        value for value in checkpoints if value['status'] == 'pending' and value.get('stoppedAfterInvalidBatch') == 1)
    assert prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
    assert invoke.call_count == 2


@pytest.mark.parametrize('version', [1, 2])
def test_reference_review_scope_reaches_the_provider_without_private_options(version):
    from jsonschema import Draft202012Validator
    from llm.responses_transport import payload
    from services.deep_research.planning_transport import options_for_record
    from services.deep_research.shared_experiment_review import CHECK_IDS_OPTION, REFERENCE_MARKER

    record, data, _ = ready()
    record[REFERENCE_MARKER] = version
    checks = verdict(record, data)['checks']
    selected = [checks[0]['checkId']]
    options = options_for_record(record, NODE, {CHECK_IDS_OPTION: selected, 'max_tokens': 4096})
    wire = payload([{'role': 'user', 'content': 'fixture'}], options, model='fixture', temperature=0)
    schema = wire['text']['format']['schema']
    assert CHECK_IDS_OPTION not in wire
    row = {**checks[0], 'planBindings': [], 'evidenceBindings': []}
    body = {'checks': [row], 'coherent': True, 'issues': []}
    validator = Draft202012Validator(schema)
    assert validator.is_valid(body)
    assert not validator.is_valid({**body, 'checks': [{**row, 'checkId': checks[1]['checkId']}]})
    assert not validator.is_valid({**body, 'checks': [row, row]})
    with pytest.raises(ValueError):
        options_for_record(record, NODE, {CHECK_IDS_OPTION: selected * 2})


def test_fact_review_wire_schema_limits_each_check_to_its_own_reference_and_text():
    from jsonschema import Draft202012Validator
    from llm.responses_transport import payload
    from services.deep_research.planning_transport import options_for_record
    from services.deep_research.shared_experiment_review import (
        CHECK_IDS_OPTION, FACT_CONTEXT_MARKER, REFERENCE_MARKER,
    )

    record, _, _ = ready()
    record.update({REFERENCE_MARKER: 2, FACT_CONTEXT_MARKER: 4})
    options = options_for_record(record, NODE, {CHECK_IDS_OPTION: ['fact_0'], 'max_tokens': 4096})
    wire = payload([{'role':'user','content':'fixture'}], options, model='fixture', temperature=0)
    assert wire['text']['format']['name'] == 'shared_experiment_review_bound_facts_v1'
    validator = Draft202012Validator(wire['text']['format']['schema'])
    row = {'checkId':'fact_0','status':'passed','planBindings':['/sourceFacts/0/text'],
           'evidenceBindings':[{'evidenceId':'E1','field':'before'}],'reason':'Fixture only'}
    def accept(check):
        return validator.is_valid({'checks':[check],'coherent':True,'issues':[]})
    assert accept(row)
    assert not accept({**row,'evidenceBindings':[{'evidenceId':'E2','field':'quote'}]})
    assert not accept({**row,'planBindings':['/sourceFacts/1/text']})


def test_reference_review_allows_bounded_multi_section_bindings_for_a_human_check():
    from jsonschema import Draft202012Validator
    from services.deep_research.shared_experiment_review import REFERENCE_MARKER

    record, _, _ = ready()
    target = next(t for t in targets(record) if t['kind'] == 'human_requirement')
    row = {'checkId':target['checkId'],'status':'passed','planBindings':[f'/steps/{i}/operation/action' for i in range(11)],
           'evidenceBindings':[],'reason':'Fixture for transport capacity only'}
    answer = {'checks':[row],'coherent':True,'issues':[]}
    record[REFERENCE_MARKER] = 2
    assert not Draft202012Validator(descriptor(record, [target['checkId']])['schema']).is_valid(answer)
    record[REFERENCE_MARKER] = 3
    validator = Draft202012Validator(descriptor(record, [target['checkId']])['schema'])
    assert validator.is_valid(answer)
    row['planBindings'].extend(f'/metrics/{i}/procedure' for i in range(6))
    assert not validator.is_valid(answer)


def test_reference_review_expands_only_a_complete_contrast_weight_vector():
    from services.deep_research.shared_experiment_review import _resolved_plan_bindings

    value = proposal()
    path = '/analysis/contrasts/0/weights'
    with pytest.raises(ValueError, match='scalar'):
        _resolved_plan_bindings([path], value, False)
    assert _resolved_plan_bindings([path], value, True) == [
        {'path':f'{path}/{index}', 'text':json.dumps(weight)}
        for index,weight in enumerate(value['analysis']['contrasts'][0]['weights'])
    ]
    with pytest.raises(ValueError, match='scalar'):
        _resolved_plan_bindings(['/groups'], value, True)


@pytest.mark.parametrize('path', ['/sourceFacts/F1/text', '/sourceFacts/0/text'])
def test_indexed_review_checks_saved_bindings_before_dispatching_next_batch(monkeypatch, path):
    from services.deep_research import shared_experiment_review as review

    record, data, aliases = ready()
    record[review.REFERENCE_MARKER] = 2
    record[review.COMPACT_REVIEW_MARKER] = 2
    checks = verdict(record, data)['checks'][:2]
    for row in checks:
        row['planBindings'] = [binding['path'] for binding in row['planBindings']]
        row['evidenceBindings'] = [{k: v for k, v in binding.items() if k != 'text'}
                                   for binding in row['evidenceBindings']]
    checks[0]['planBindings'] = [path]
    request_ids = [[row['checkId']] for row in checks]
    batches = [{'checkIds': ids, 'suppliedEvidenceAliases': list(aliases),
                'request': {'prompt': 'fixture', 'extra': {review.CHECK_IDS_OPTION: ids}}}
               for ids in request_ids]
    monkeypatch.setattr(review, 'build', lambda *args, **kwargs: {
        'batches': batches, 'inputBytes': 100, 'hardIssues': [], 'targets': targets(record),
        review.STOP_INVALID_BATCH_MARKER: 1, review.REFERENCE_MARKER: 2})
    monkeypatch.setattr('services.deep_research.planning_transport.dispatch_options', lambda *args: {})
    invoke = Mock(side_effect=[reply({'checks': [row], 'coherent': True, 'issues': []}) for row in checks])
    checkpoints = []

    def checkpoint(value):
        record['state']['sharedExperimentReview'] = deepcopy(value)
        checkpoints.append(deepcopy(value))

    result = prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint)
    invalid = path == '/sourceFacts/F1/text'
    assert invoke.call_count == (1 if invalid else 2)
    assert result.get('stoppedAfterInvalidBatch') == (0 if invalid else None)
    if invalid:
        assert result['status'] == 'invalid_response'
        saved = next(value for value in checkpoints if value['status'] == 'pending' and value.get('batchResponses'))
        record['state']['sharedExperimentReview'] = saved
        assert prepare(record, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
        assert invoke.call_count == 1


@pytest.mark.parametrize('mutation', ['missing','duplicate','unknown','fake_plan','wrong_section','identifier_only',
                                    'missing_fact_evidence','foreign_evidence','nonliteral_evidence','coherence',
                                    'truncated','duplicate_json'])
def test_malformed_or_unbound_positive_verdict_never_grants_approval(mutation):
    r,data,aliases=ready(); v=verdict(r,data); response=None
    if mutation=='missing': v['checks'].pop()
    elif mutation=='duplicate': v['checks'][-1]=deepcopy(v['checks'][0])
    elif mutation=='unknown': v['checks'][0]['checkId']='unknown'
    elif mutation=='fake_plan': v['checks'][0]['planBindings'][0]['text']='invented'
    elif mutation=='wrong_section': v['checks'][2]['planBindings']=[{'path':'/hypothesis','text':_pointer(r['state']['sharedExperimentGeneration']['boundProposal']['proposal'],'/hypothesis')}]
    elif mutation=='identifier_only': v['checks'][0]['planBindings']=[{'path':'/sourceFacts/0/id','text':'F1'}]
    elif mutation=='missing_fact_evidence': v['checks'][0]['evidenceBindings']=[]
    elif mutation=='foreign_evidence': v['checks'][0]['evidenceBindings'][0]['evidenceId']='E2'
    elif mutation=='nonliteral_evidence': v['checks'][0]['evidenceBindings'][0]['text']='unsupported original quote'
    elif mutation=='coherence': v['coherent']=False
    elif mutation=='truncated': response={**reply(v),'finishReason':'length'}
    else: response={**reply(v),'content':reply(v)['content'].replace('"coherent": true','"coherent": true,"coherent":true')}
    result=assess(r,data,aliases,response or reply(v))
    assert result['valid'] is False and result['scientificApproval'] is False


def test_failed_scientific_check_remains_a_real_gap_and_cannot_compile_a_result():
    r,data,aliases=ready(); v=verdict(r,data)
    v['checks'][3].update(status='failed',reason='初始化操作与实际表示不兼容。')
    result,_,_,_=check(r,data,aliases,v)
    assert result['assessment']['valid'] and not result['assessment']['complete']
    with pytest.raises(DeepResearchError) as error: compile_candidate(r,data,aliases)
    assert error.value.code=='shared_experiment_incomplete'


def test_negative_review_may_bind_actual_availability_or_identity_without_becoming_invalid():
    r,data,aliases=ready();v=verdict(r,data)
    v['checks'][2].update(status='unresolved',reason='需要进一步确认实际准备步骤。',
        planBindings=[{'path':'/data/inputs/0/availability','text':'prepare'}])
    v.update(coherent=False,issues=[{'reason':'初始化依赖尚未解决。',
        'planBindings':[{'path':'/states/0/id','text':'raw'}]}])
    result=assess(r,data,aliases,reply(v))
    assert result['valid'] and not result['scientificApproval']


def test_unresolved_prerequisite_cannot_be_waived_by_all_passed_model_checks():
    p=proposal(); p['unresolved']=['Required initial asset has no preparation recipe.']
    r,data,aliases=ready(p); result,_,_,_=check(r,data,aliases)
    assert result['assessment']['valid'] and not result['assessment']['scientificApproval']


def test_existing_number_precheck_stops_before_independent_model_request():
    p=proposal(); p['sourceFacts'][0]['text']='The paper reports 999 MB of storage.'
    r,data,aliases=ready(p); sent=Mock(); saved=[]
    result=prepare(r,data,aliases,invoke=sent,checkpoint=saved.append)
    assert result['status']=='not_started_precheck' and result['hardIssues']
    sent.assert_not_called()
    assert assess(r,data,aliases,reply(verdict(r,data)))['scientificApproval'] is False


@pytest.mark.parametrize(('origin', 'formula', 'reason'), [
    ('', 'floor', 'split_index_origin_missing'),
    ('Use zero-based indices. ', 'floor', 'split_holdout_count_mismatch'),
    ('Use one-based indices. ', 'ceil', 'split_holdout_count_mismatch'),
    ('Use one-based indices. ', 'floor', None),
    ('Use zero-based indices. ', 'ceil', None),
    ('Use zero-based indices. If N is divisible by 8, ', 'floor', None),
])
def test_modulo_split_verifies_count_without_confusing_index_origins(origin, formula, reason):
    from services.deep_research.shared_experiment_protocol_checks import detect

    p = proposal()
    p['data']['splitPrecheck'] = f'{origin}Select i mod 8 = 0. Test count equals {formula}(N/8).'
    issues = detect(p)
    assert [issue['reason'] for issue in issues] == ([reason] if reason else [])
    if reason == 'split_holdout_count_mismatch':
        witness, = issues
        start = 0 if 'zero' in origin else 1
        n = witness['exampleImageCount']
        assert witness['selected'] == sum(i % 8 == 0 for i in range(start, start + n))
        assert witness['selected'] != witness['claimed']


def test_paired_arm_defect_reaches_precheck_without_reviewer_call():
    from services.deep_research.shared_experiment_protocol_checks import MARKER, detect

    p = proposal()
    p['data']['independentUnit'] = 'One trained arm on one selected scene is one independent unit.'
    record, data, aliases = ready(p)
    record[MARKER] = 1
    invoke = Mock()
    result = prepare(record, data, aliases, invoke=invoke, checkpoint=Mock())
    assert result['status'] == 'not_started_precheck'
    assert result['hardIssues'] == [
        {'path': '/data/independentUnit', 'reason': 'paired_arm_is_not_independent_replicate'}]
    invoke.assert_not_called()
    assert not assess(record, data, aliases, reply(verdict(record, data)))['valid']

    p['data']['independentUnit'] = 'Each arm is not an independent unit; the matched scene and seed is the block.'
    assert detect(p) == []


def test_protocol_checks_recognize_direct_chinese_assertions():
    from services.deep_research.shared_experiment_protocol_checks import detect

    p = proposal()
    p['data']['splitPrecheck'] = '索引从0开始。选 i % 8 == 0，测试图像数应等于 floor(N/8)。'
    p['data']['independentUnit'] = '每个实验组是一个独立重复单位。'
    assert [issue['reason'] for issue in detect(p)] == [
        'split_holdout_count_mismatch', 'paired_arm_is_not_independent_replicate']


def test_unknown_review_is_preserved_and_not_automatically_repeated():
    r,data,aliases=ready(); sent=Mock(side_effect=UnknownCallError('original'))
    def checkpoint(v): r['state']['sharedExperimentReview']=deepcopy(v)
    with pytest.raises(UnknownCallError): prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    with pytest.raises(DeepResearchError): prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    assert sent.call_count==1


def test_candidate_is_compiled_from_same_definitions_and_still_requires_final_audit():
    r,data,aliases=ready(); check(r,data,aliases)
    result=compile_candidate(r,data,aliases)
    assert result['publishable'] is False and result['finalAnswerAuditRequired'] is True
    assert validate_candidate(result,r,data,aliases)
    assert result['citations'][0]['evidenceId']==aliases['E1']
    assert '尚未执行' in result['markdown'] and '999' not in result['markdown']
    assert 'SH coefficients' in result['markdown'] and 'scale and rotation' in result['markdown']
    assert '训练划分' in result['markdown'] and '100 优化步' in result['markdown'] and '10 优化步' in result['markdown']
    result['markdown']+='\nInvented extra result.'
    assert not validate_candidate(result,r,data,aliases)


@pytest.mark.parametrize('mutation',['proposal','review_response','review_verdict','evidence','budget_limit'])
def test_edit_after_review_cannot_reuse_result_or_approval(mutation):
    r,data,aliases=ready(); check(r,data,aliases)
    if mutation=='proposal': r['state']['sharedExperimentGeneration']['boundProposal']['proposal']['budgets'][1]['cap']=999
    elif mutation=='review_response': r['state']['sharedExperimentReview']['response']['content']='{}'
    elif mutation=='review_verdict': r['state']['sharedExperimentReview']['assessment']['verdict']['checks'][0]['reason']='rewritten'
    elif mutation=='evidence': data['evidence'][0]['quote']='changed source'
    else: r['budget']['maxTokens']+=1
    with pytest.raises((DeepResearchError,ValueError)): compile_candidate(r,data,aliases)


def test_actual_scoped_tracked_review_schema_and_reuse(tmp_path,monkeypatch):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response as http_response
    r,data,aliases=ready(); repo=DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    repo.create_run(r); repo.begin_execution('r')
    post=Mock(return_value=http_response(json.dumps(verdict(r,data))))
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    client=ScopedModelClient(repo,lambda *args:True,lambda:provider).for_run('r')
    invoker=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    def checkpoint(v): repo.update_run('r',lambda r:{**r,'state':{**r['state'],'sharedExperimentReview':deepcopy(v)}})
    def run(): return prepare(repo.require_run('r'),data,aliases,checkpoint=checkpoint,
        invoke=lambda node,prompt,opts:invoker('r',node,prompt,opts,use_reserve=True))
    result=run()
    assert result['assessment']['complete'] and result['status']=='checked'
    assert run()==result and post.call_count==1
    assert repo.list_calls('r')[0]['argsDigest']==digest(result['request'])
    wire=post.call_args.kwargs['json']
    assert wire['text']['format']==descriptor(repo.require_run('r')) and wire['max_output_tokens']==4096
    assert invoker.prompt_byte_limit('r',NODE)==32000
