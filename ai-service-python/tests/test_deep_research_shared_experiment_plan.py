from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research.contracts import digest
from services.deep_research.shared_experiment_plan import (
    GROUPS, CONTRASTS, schema, validate, bind_for_review as bind, validate_bound)


def bind_for_review(value, evidence_ids, **kwargs):
    return bind(value, evidence_ids, context_digest=digest('handwritten frozen context'), **kwargs)


def operation(action, value=4):
    return {'action': action, 'parameters': [{'name': 'setting', 'type': 'number', 'value': value}]}


def proposal(method='compression'):
    # Handwritten interface fixtures, never real model output/scientific acceptance.
    meanings = ('SH coefficients', 'scale and rotation') if method == 'compression' else ('index precision', 'cache policy')
    factors = [{'id': fid, 'label': label, 'affectedStateIds': [sid], 'offStateMode': 'retain',
                'offOperation': operation('Retain original '+label, 0),
                'onOperation': operation('Apply proposed '+label)}
               for fid, sid, label in zip(('A', 'B'), ('x', 'y'), meanings)]
    states = [{'id': 'raw', 'meaning': 'Common preparation output', 'representation': 'Named complete source state',
               'scope': 'shared', 'groups': [], 'fixed': False, 'persisted': False, 'source': {'kind': 'input', 'id': 'input'}}]
    states += [{'id': sid, 'meaning': label, 'representation': 'Original precision or proposed encoding, recorded in manifest',
                'scope': 'arm', 'groups': list(GROUPS), 'fixed': False, 'persisted': True, 'source': {'kind': 'step', 'id': 'copy'}}
               for sid, label in zip(('x', 'y'), meanings)]
    def step(sid, kind, *, scope='arm', groups=GROUPS, reads=(), creates=(), updates=(), budget=None,
             data_use='none', factor=None, metrics=(), op=None):
        return {'id': sid, 'scope': scope, 'groups': list(groups), 'kind': kind,
                'dataUse': data_use, 'factor': factor, 'metricIds': list(metrics),
                'reads': list(reads), 'creates': list(creates), 'updates': list(updates),
                'operation': op or operation(kind), 'budgetId': budget}
    steps = [step('baseline', 'fit', scope='shared', groups=(), reads=['raw'], updates=['raw'],
                  budget='common', data_use='training'),
             step('copy', 'clone', reads=['raw'], creates=['x', 'y'])]
    for f in factors:
        for level in (0, 1):
            arms = [g for g in GROUPS if int(g[0 if f['id']=='A' else 1]) == level]
            steps.append(step(f['id']+str(level), 'intervene', groups=arms,
                              reads=f['affectedStateIds'], updates=f['affectedStateIds'] if level else [],
                              factor={'id': f['id'], 'level': level},
                              op=deepcopy(f['onOperation' if level else 'offOperation'])))
    steps += [step('recovery', 'fit', reads=['x', 'y'], updates=['x', 'y'], budget='matched', data_use='training'),
              step('evaluate', 'measure', reads=['x', 'y'], data_use='evaluation', metrics=['quality', 'size', 'latency'])]
    return {'version': 1, 'hypothesis': 'Estimate the two main effects and their interaction.',
            'estimand': 'Paired effects at the declared levels, not all possible settings.',
            'sourceFacts': [{'id': 'F1', 'text': 'Fixture source statement, not a measured result.', 'evidenceRefs': ['E1']}],
            'data': {'inputs': [{'id': 'input', 'description': 'Public training inputs', 'availability': 'prepare',
                                 'preparation': 'Enumerate inputs, create common state using fixed training-only seed; save its manifest.',
                                 'sourceFactIds': ['F1']}],
                     'trainingSplit': 'Persist sorted training IDs before fitting.',
                     'evaluationSplit': 'Persist disjoint held-out IDs before fitting.',
                     'splitPrecheck': 'Stop for duplicate IDs, overlap or an empty side.',
                     'selectionUses': 'training_only', 'independentUnit': 'Independent paired scene', 'seeds': [7, 13]},
            'states': states,
            'pairing': {'sharedStateIds': ['raw'], 'cloneStepIds': ['copy'],
                        'identityChecks': 'Verify matching source checksum, element identities, counts and initial values.'},
            'factors': factors,
            'groups': [{'id': g, 'levels': {'A': int(g[0]), 'B': int(g[1])}} for g in GROUPS],
            'budgets': [{'id': 'common', 'unit': 'optimizer_steps', 'cap': 100, 'scope': 'shared',
                         'groups': [], 'matching': 'equal', 'stopRule': 'Stop at fixed common cap.'},
                        {'id': 'matched', 'unit': 'optimizer_steps', 'cap': 10, 'scope': 'arm',
                         'groups': list(GROUPS), 'matching': 'equal', 'stopRule': 'Use the same cap per arm.'}],
            'steps': steps,
            'metrics': [{'id': mid, 'domain': domain, 'unit': unit, 'direction': direction,
                         'procedure': 'Measure under the saved common conditions; record actual values.', 'stateIds': ['x', 'y']}
                        for mid, domain, unit, direction in [('quality', 'quality', 'dB', 'higher_better'),
                                                           ('size', 'storage', 'bytes', 'lower_better'),
                                                           ('latency', 'speed', 'milliseconds', 'lower_better')]],
            'analysis': {'lossConvention': 'negate_higher_better',
                         'contrasts': [{'kind': k, 'weights': deepcopy(v)} for k, v in CONTRASTS.items()],
                         'metricIds': ['quality', 'size', 'latency'],
                         'uncertainty': 'Pair per scene and seed; do not treat nearby views as independent.',
                         'decisionRule': 'Report effects and uncertainty, not independence from a non-significant test.',
                         'limitations': 'These two levels and sampled scenes bound interpretation.'},
            'unresolved': []}


@pytest.mark.parametrize('method', ['compression', 'retrieval'])
def test_shared_contract_is_not_paper_specific_or_a_scientific_approval(method):
    value = proposal(method); before = deepcopy(value)
    Draft202012Validator.check_schema(schema())
    assert validate(value, ['E1'], required_domains=['quality', 'storage', 'speed']) == []
    bound = bind_for_review(value, ['E1'], required_domains=['quality', 'storage', 'speed'])
    assert validate_bound(bound, expected_digest=bound['bindingDigest'])
    assert bound['scientificApproval'] is False and bound['status'] == 'awaiting_scientific_review'
    assert 'publication' not in bound and value == before
    assert len(json.dumps(value, ensure_ascii=False).encode()) < 16000


@pytest.mark.parametrize('mutation,code', [
    ('levels', 'plan.factorial_groups'), ('duplicate_group', 'plan.duplicate_identity'),
    ('factor_operation', 'plan.intervention_operation'), ('factor_level', 'plan.intervention_level'),
    ('missing_intervention', 'plan.intervention_coverage'), ('future_read', 'plan.future_state'),
    ('fixed_update', 'plan.fixed_state_update'), ('shared_update', 'plan.fixed_state_update'),
    ('unpaired', 'plan.unpaired_groups'), ('foreign_evidence', 'plan.foreign_evidence'),
    ('provided_without_provenance', 'plan.input_provenance'), ('missing_state_source', 'plan.state_source'),
    ('test_fit', 'plan.evaluation_leakage'), ('measurement_mutation', 'plan.measurement_mutation'),
    ('early_measurement', 'plan.measurement_before_treatment'), ('late_mutation', 'plan.post_measurement_mutation'),
    ('budget_missing_arm', 'plan.budget_allocation'), ('budget_subset', 'plan.unmatched_budget'),
    ('duplicate_fit', 'plan.budget_allocation'), ('fractional_steps', 'plan.budget_integer'),
    ('omit_storage_state', 'plan.incomplete_resource_accounting'), ('omit_metric', 'plan.analysis_metrics'),
    ('telescoping_interaction', 'plan.contrast_weights'), ('missing_domain', 'plan.missing_measurement_domain'),
])
def test_scientific_counterexamples_do_not_enter_review_as_structurally_valid(mutation, code):
    p = proposal()
    if mutation == 'levels': p['groups'][1]['levels']['A'] = 0
    elif mutation == 'duplicate_group': p['groups'][1] = deepcopy(p['groups'][0])
    elif mutation == 'factor_operation': p['steps'][3]['operation'] = operation('Unrelated intervention')
    elif mutation == 'factor_level': p['steps'][3]['factor']['level'] = 0
    elif mutation == 'missing_intervention': p['steps'].pop(3)
    elif mutation == 'future_read': p['steps'].insert(0, p['steps'].pop(2))
    elif mutation == 'fixed_update': p['states'][1]['fixed'] = True
    elif mutation == 'shared_update': p['steps'][-2]['updates'].append('raw')
    elif mutation == 'unpaired': p['steps'][1]['groups'] = ['00']
    elif mutation == 'foreign_evidence': p['sourceFacts'][0]['evidenceRefs'] = ['E2']
    elif mutation == 'provided_without_provenance':
        p['data']['inputs'][0].update(availability='provided', sourceFactIds=[])
    elif mutation == 'missing_state_source': p['states'][1]['source']['id'] = 'missing'
    elif mutation == 'test_fit': p['steps'][-2]['dataUse'] = 'evaluation'
    elif mutation == 'measurement_mutation': p['steps'][-1]['updates'] = ['x']
    elif mutation == 'early_measurement': p['steps'].insert(2, p['steps'].pop())
    elif mutation == 'late_mutation': p['steps'].append(p['steps'].pop(-2))
    elif mutation == 'budget_missing_arm': p['steps'][-2]['groups'] = ['00', '10', '01']
    elif mutation == 'budget_subset': p['budgets'][1]['groups'] = ['00', '10', '01']
    elif mutation == 'duplicate_fit':
        row = deepcopy(p['steps'][-2]); row['id'] = 'extra_fit'; p['steps'].insert(-1, row)
    elif mutation == 'fractional_steps': p['budgets'][1]['cap'] = 1.5
    elif mutation == 'omit_storage_state': p['metrics'][1]['stateIds'] = ['x']
    elif mutation == 'omit_metric': p['analysis']['metricIds'].pop()
    elif mutation == 'telescoping_interaction': p['analysis']['contrasts'][2]['weights'] = [-1, 1, 0, 0]
    elif mutation == 'missing_domain': p['metrics'][2]['domain'] = 'quality'
    before = deepcopy(p)
    issues = validate(p, ['E1'], required_domains=['quality', 'storage', 'speed'])
    assert code in {row['code'] for row in issues}
    assert p == before
    with pytest.raises(ValueError): bind_for_review(p, ['E1'], required_domains=['quality', 'storage', 'speed'])


@pytest.mark.parametrize('value', [None, [], {}, {'version': True}, {'version': float('nan')}])
def test_malformed_plan_fails_without_repair_or_default_values(value):
    assert validate(value, ['E1'])


@pytest.mark.parametrize('mutation', ['proposal', 'evidence_scope', 'domains', 'context', 'status', 'approval', 'rehashed'])
def test_later_edit_cannot_reuse_the_bound_review_identity(mutation):
    bound = bind_for_review(proposal(), ['E1'], required_domains=['quality'])
    original = bound['bindingDigest']
    if mutation in ('proposal', 'rehashed'): bound['proposal']['budgets'][1]['cap'] = 20
    elif mutation == 'evidence_scope': bound['allowedEvidenceIds'].append('E2')
    elif mutation == 'domains': bound['requiredDomains'] = []
    elif mutation == 'context': bound['contextDigest'] = digest('another paper or question')
    elif mutation == 'status': bound['status'] = 'passed'
    else: bound['scientificApproval'] = True
    if mutation == 'rehashed':
        bound['proposalDigest'] = digest(bound['proposal'])
        bound['bindingDigest'] = digest({k:v for k,v in bound.items() if k != 'bindingDigest'})
    assert not validate_bound(bound, expected_digest=original)


def test_source_facts_and_well_formed_procedures_still_require_semantic_review():
    p = proposal()
    p['hypothesis'] = 'This scientifically false sentence must not be approved by a shape checker.'
    bound = bind_for_review(p, ['E1'])
    assert bound['scientificApproval'] is False
    assert validate_bound(bound, expected_digest=bound['bindingDigest'])


def test_treatment_only_codebook_is_counted_only_where_active_without_inventing_control_states():
    p = proposal()
    p['states'].append({'id':'codebook', 'meaning':'Treatment-only lookup table',
        'representation':'Explicit proposed quantizer table', 'scope':'arm', 'groups':['10', '11'],
        'fixed':False, 'persisted':True, 'source':{'kind':'step', 'id':'A1'}})
    p['steps'][3]['creates'] = ['codebook']
    for metric in p['metrics']: metric['stateIds'].append('codebook')
    assert not validate(p, ['E1'])
    # The state is declared for both treatment arms; creating it for only one
    # cannot be concealed by a whole-answer metric declaration.
    p['steps'][3]['groups'] = ['10']
    codes = {i['code'] for i in validate(p, ['E1'])}
    assert 'plan.measurement_state_unavailable' in codes


def test_binding_requires_frozen_context_and_scope_without_consumable_iterators():
    with pytest.raises(ValueError): bind(proposal(), ['E1'], context_digest='missing')
    assert validate(proposal(), iter(['E1'])) == [{'code':'plan.review_scope', 'path':'/'}]
    assert validate(proposal(), ['E1'], required_domains=['unknown'])
