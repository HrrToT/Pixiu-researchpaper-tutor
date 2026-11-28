"""One unexecuted binary-factorial proposal, not a scientific verdict.

Shared definitions own state, groups, execution and accounting. This candidate
contract is not enabled by the facade and does not replace legacy validators.
"""
from copy import deepcopy
from collections import Counter
import json
import re

from services.deep_research.contracts import digest

MAX_BYTES = 24000
MAX_EXPANDED_BYTES = 32000
EVALUATION_PREPARATION_MARKER = 'sharedExperimentEvaluationPreparationVersion'
OPERATION_CAPACITY_MARKER = 'sharedExperimentOperationCapacityVersion'
GROUPS = ('00', '10', '01', '11')
CONTRASTS = {
    'A': [-0.5, 0.5, -0.5, 0.5],
    'B': [-0.5, -0.5, 0.5, 0.5],
    'interaction': [1, -1, -1, 1],
}


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def _array(items, minimum=0, maximum=32, unique=False):
    return {'type': 'array', 'items': items, 'minItems': minimum, 'maxItems': maximum,
            **({'uniqueItems': True} if unique else {})}


def schema(version=1, *, evaluation_prepare=False):
    text = {'type': 'string', 'minLength': 1, 'maxLength': 1600, 'pattern': r'\S'}
    ident = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,47}$'}
    ids = _array(ident, maximum=32, unique=True)
    parameter = _object({'name': ident, 'type': {'enum': ['number', 'choice']},
                         'value': {'type': ['number', 'string']}})
    operation = _object({'action': text, 'parameters': _array(parameter, maximum=24)})
    plan = _object({
        'version': {'const': version, 'type': 'integer'},
        'hypothesis': text,
        'estimand': text,
        'sourceFacts': _array(_object({'id': ident, 'text': text, 'evidenceRefs': _array(ident, 1, 20, True)}), maximum=20),
        'data': _object({
            'inputs': _array(_object({'id': ident, 'description': text, 'availability': {'enum': ['provided', 'prepare']},
                                     'preparation': text, 'sourceFactIds': ids}), 1, 8),
            'trainingSplit': text, 'evaluationSplit': text, 'splitPrecheck': text,
            'selectionUses': {'const': 'training_only'}, 'independentUnit': text,
            'seeds': _array({'type': 'integer', 'minimum': 0, 'maximum': 4294967295}, 1, 32, True)}),
        'states': _array(_object({'id': ident, 'meaning': text, 'representation': text,
                                  'scope': {'enum': ['shared', 'arm']}, 'fixed': {'type': 'boolean'},
                                  'groups': _array({'enum': list(GROUPS)}, maximum=4, unique=True),
                                  'persisted': {'type': 'boolean'},
                                  'source': _object({'kind': {'enum': ['input', 'step']}, 'id': ident})}), 1, 32),
        'pairing': _object({'sharedStateIds': ids, 'cloneStepIds': _array(ident, 1, 16, True),
                            'identityChecks': text}),
        'factors': _array(_object({'id': {'enum': ['A', 'B']}, 'label': text,
                                   'affectedStateIds': _array(ident, 1, 16, True),
                                   'offStateMode': {'const': 'retain'},
                                   'offOperation': operation, 'onOperation': operation}), 2, 2),
        'groups': _array(_object({'id': {'enum': list(GROUPS)},
                                  'levels': _object({'A': {'enum': [0, 1], 'type': 'integer'},
                                                     'B': {'enum': [0, 1], 'type': 'integer'}})}), 4, 4),
        'budgets': _array(_object({'id': ident, 'unit': {'enum': ['optimizer_steps', 'epochs', 'wall_seconds']},
                                   'cap': {'type': 'number', 'minimum': 0},
                                   'scope': {'enum': ['shared', 'arm']},
                                   'groups': _array({'enum': list(GROUPS)}, maximum=4, unique=True),
                                   'matching': {'enum': ['equal', 'native']},
                                   'stopRule': text}), 1, 16),
        'steps': _array(_object({'id': ident, 'scope': {'enum': ['shared', 'arm']},
                                 'groups': _array({'enum': list(GROUPS)}, maximum=4, unique=True),
                                 'kind': {'enum': ['prepare', 'clone', 'intervene', 'fit', 'measure']},
                                 'dataUse': {'enum': ['training', 'evaluation', 'none']
                                             + (['evaluation_prepare'] if version == 3 and evaluation_prepare else [])},
                                 'factor': {'anyOf': [{'type': 'null'}, _object({
                                     'id': {'enum': ['A', 'B']}, 'level': {'enum': [0, 1], 'type': 'integer'}})]},
                                 'metricIds': ids,
                                 'reads': ids, 'creates': ids, 'updates': ids,
                                 'operation': operation, 'budgetId': {'type': ['string', 'null']}}), 1, 32),
        'metrics': _array(_object({'id': ident, 'domain': {'enum': ['quality', 'storage', 'speed', 'memory']},
                                   'unit': text, 'direction': {'enum': ['higher_better', 'lower_better']},
                                   'procedure': text, 'stateIds': ids}), 1, 12),
        'analysis': _object({'lossConvention': {'const': 'negate_higher_better'},
                             'contrasts': _array(_object({'kind': {'enum': list(CONTRASTS)},
                                                          'weights': _array({'type': 'number'}, 4, 4)}), 3, 3),
                             'metricIds': _array(ident, 1, 12, True),
                             'uncertainty': text, 'decisionRule': text, 'limitations': text}),
        'unresolved': _array(text, maximum=16),
    })
    if version in (2, 3):
        step = plan['properties']['steps']['items']
        step['properties']['inputIds'] = _array(ident, maximum=8, unique=True)
        step['required'].append('inputIds')
    if version == 3:
        budget = plan['properties']['budgets']['items']
        budget['properties']['allocation'] = {'enum': ['single', 'shared_preparation_total']}
        budget['required'].append('allocation')
        metric = plan['properties']['metrics']['items']
        metric['properties']['fitMemoryCaptures'] = _array(_object({'stepId': ident, 'recordStateId': ident}), maximum=32)
        metric['required'].append('fitMemoryCaptures')
    return plan


def _counted_size(value, serialized_size):
    """Exclude only exact compiler copies of factor operations."""
    factors = {factor['id']: factor for factor in value['factors']}
    for step in value['steps']:
        selection = step['factor']
        if step['kind'] != 'intervene' or selection is None:
            continue
        source = factors.get(selection['id'], {}).get('onOperation' if selection['level'] else 'offOperation')
        if source == step['operation']:
            copy_size = len(json.dumps(source, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            serialized_size -= copy_size - len('null')
    return serialized_size


def validate(value, evidence_ids, *, required_domains=(), count_unique_operations=False):
    """Check known identities/causality/accounting; prose needs scientific review."""
    from jsonschema import Draft202012Validator
    from services.deep_research.group_spec import validate_operation
    if (not isinstance(evidence_ids, (list, tuple, set, frozenset))
            or any(not isinstance(e, str) or not e for e in evidence_ids)
            or not isinstance(required_domains, (list, tuple, set, frozenset))
            or any(not isinstance(d, str) or d not in {'quality', 'storage', 'speed', 'memory'} for d in required_domains)):
        return [{'code': 'plan.review_scope', 'path': '/'}]
    allowed_evidence = set(evidence_ids)
    issues = []
    def issue(code, path):
        issues.append({'code': code, 'path': path})
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        size = len(encoded.encode('utf-8'))
        if size > (MAX_EXPANDED_BYTES if count_unique_operations else MAX_BYTES):
            return [{'code': 'plan.capacity', 'path': '/'}]
    except (TypeError, ValueError, OverflowError, RecursionError):
        return [{'code': 'plan.json', 'path': '/'}]
    version = value.get('version') if isinstance(value, dict) else None
    typed_inputs = type(version) is int and version in (2, 3)
    errors = list(Draft202012Validator(schema(version if typed_inputs else 1, evaluation_prepare=True)).iter_errors(value))
    if errors:
        return [{'code': 'plan.schema', 'path': '/'+'/'.join(map(str, e.absolute_path))} for e in errors[:64]]
    if size > MAX_BYTES and (version != 3 or _counted_size(value, size) > MAX_BYTES):
        return [{'code': 'plan.capacity', 'path': '/'}]
    def indexed(rows, path):
        if len({row['id'] for row in rows}) != len(rows):
            issue('plan.duplicate_identity', path)
        return {row['id']: row for row in rows}
    facts = indexed(value['sourceFacts'], '/sourceFacts')
    inputs = indexed(value['data']['inputs'], '/data/inputs')
    states = indexed(value['states'], '/states')
    steps = indexed(value['steps'], '/steps')
    budgets = indexed(value['budgets'], '/budgets')
    metrics = indexed(value['metrics'], '/metrics')
    groups = indexed(value['groups'], '/groups')
    for index, row in enumerate(value['sourceFacts']):
        if not set(row['evidenceRefs']) <= allowed_evidence:
            issue('plan.foreign_evidence', f'/sourceFacts/{index}/evidenceRefs')
    for index, row in enumerate(value['data']['inputs']):
        if not set(row['sourceFactIds']) <= set(facts) or row['availability'] == 'provided' and not row['sourceFactIds']:
            issue('plan.input_provenance', f'/data/inputs/{index}')
    if set(groups) != set(GROUPS) or any(
            groups[g]['levels'] != {'A': int(g[0]), 'B': int(g[1])} for g in groups):
        issue('plan.factorial_groups', '/groups')
    if {f['id'] for f in value['factors']} != {'A', 'B'}:
        issue('plan.factor_identity', '/factors')
    if any(i['code'] in ('plan.duplicate_identity', 'plan.factorial_groups', 'plan.factor_identity') for i in issues):
        return issues
    for i, factor in enumerate(value['factors']):
        if any(s not in states or states[s]['scope'] != 'arm' or set(states[s]['groups']) != set(GROUPS)
               for s in factor['affectedStateIds']):
            issue('plan.factor_state', f'/factors/{i}/affectedStateIds')
        for side in ('offOperation', 'onOperation'):
            if validate_operation(factor[side]): issue('plan.operation', f'/factors/{i}/{side}')
    for i, state in enumerate(value['states']):
        source = state['source']; path = f'/states/{i}/source'
        if state['scope'] == 'shared' and state['groups'] or state['scope'] == 'arm' and not state['groups']:
            issue('plan.state_scope', f'/states/{i}/groups')
        if source['kind'] == 'input':
            if (source['id'] not in inputs or state['scope'] != 'shared'
                    or typed_inputs and inputs[source['id']]['availability'] != 'provided'):
                issue('plan.state_source', path)
        elif source['id'] not in steps or state['id'] not in steps[source['id']]['creates']:
            issue('plan.state_source', path)
    shared = {s['id'] for s in value['states'] if s['source']['kind'] == 'input'}
    available = {g: set() for g in GROUPS}
    allocations = Counter()
    treatments = Counter()
    measurements = Counter()
    measured_groups = set()
    factors = {f['id']: f for f in value['factors']}
    ready_inputs = {i['id'] for i in inputs.values() if i['availability'] == 'provided'}
    evaluation_states = {sid for step in value['steps'] if step['dataUse'] == 'evaluation_prepare'
                         for sid in step['creates']}
    for i, step in enumerate(value['steps']):
        path = f'/steps/{i}'
        evaluation_prepare = step['dataUse'] == 'evaluation_prepare'
        if typed_inputs:
            assets = set(step['inputIds'])
            if not assets <= inputs.keys():
                issue('plan.step_input_identity', path+'/inputIds')
            elif step['kind'] == 'prepare' and step['scope'] == 'shared' and not evaluation_prepare:
                ready_inputs.update(assets)
            elif not assets <= ready_inputs:
                issue('plan.step_input_unavailable', path+'/inputIds')
            if assets and step['kind'] != 'prepare' and step['dataUse'] == 'none':
                issue('plan.step_input_without_data_scope', path+'/inputIds')
        if validate_operation(step['operation']): issue('plan.operation', path+'/operation')
        if step['scope'] == 'shared' and step['groups'] or step['scope'] == 'arm' and not step['groups']:
            issue('plan.step_scope', path)
        if step['dataUse'] == 'evaluation' and step['kind'] != 'measure':
            issue('plan.evaluation_leakage', path+'/dataUse')
        if evaluation_prepare:
            budget = budgets.get(step['budgetId'])
            if (step['kind'] != 'prepare' or step['scope'] != 'shared' or step['updates'] or not step['creates']
                    or any(sid not in states or not states[sid]['fixed'] for sid in step['reads'] + step['creates'])
                    or not budget or budget['scope'] != 'shared' or budget['unit'] != 'wall_seconds'
                    or budget['cap'] <= 0):
                issue('plan.evaluation_preparation_scope', path)
        evaluation_reader = evaluation_prepare or step['kind'] == 'measure' and step['dataUse'] == 'evaluation'
        if not evaluation_reader and evaluation_states.intersection(step['reads']):
            issue('plan.evaluation_state_leakage', path+'/reads')
        if evaluation_states.intersection(step['updates']):
            issue('plan.evaluation_state_leakage', path+'/updates')
        evaluation_required = {sid for mid in step['metricIds'] if mid in metrics
                               for sid in metrics[mid]['stateIds'] if sid in evaluation_states}
        if evaluation_required and (not evaluation_reader or not evaluation_required <= set(step['reads'])):
            issue('plan.evaluation_state_leakage', path+'/metricIds')
        if step['kind'] == 'measure' and (step['creates'] or step['updates']):
            issue('plan.measurement_mutation', path)
        if step['kind'] == 'measure':
            if step['scope'] != 'arm' or not step['metricIds'] or not set(step['metricIds']) <= set(metrics):
                issue('plan.measurement_reference', path)
            measurements.update((mid, g) for mid in step['metricIds'] for g in step['groups'])
            if any(treatments[(f, g)] != 1 for f in ('A', 'B') for g in step['groups']):
                issue('plan.measurement_before_treatment', path)
            measured_groups.update(step['groups'])
        elif step['metricIds']:
            issue('plan.measurement_reference', path)
        if (set(step['groups']) & measured_groups and step['kind'] != 'measure'
                and (step['creates'] or step['updates'] or step['kind'] == 'intervene')):
            issue('plan.post_measurement_mutation', path)
        factor = step['factor']
        if step['kind'] == 'intervene':
            if factor is None or step['scope'] != 'arm':
                issue('plan.intervention_reference', path)
            elif factor['id'] in factors:
                declared = factors[factor['id']]
                expected_op = declared['onOperation' if factor['level'] else 'offOperation']
                if step['operation'] != expected_op or not set(declared['affectedStateIds']) <= set(step['reads']):
                    issue('plan.intervention_operation', path)
                for g in step['groups']:
                    if groups[g]['levels'][factor['id']] != factor['level']:
                        issue('plan.intervention_level', path)
                    treatments[(factor['id'], g)] += 1
        elif factor is not None:
            issue('plan.intervention_reference', path)
        if step['kind'] == 'fit' and (step['dataUse'] != 'training' or step['budgetId'] is None):
            issue('plan.fit_contract', path)
        targets = step['groups'] if step['scope'] == 'arm' else [None]
        for g in targets:
            ready = shared | available[g] if g is not None else shared
            if not set(step['reads'] + step['updates']) <= ready:
                issue('plan.future_state', path)
            for sid in step['updates']:
                if sid not in states or states[sid]['fixed'] or g is not None and states[sid]['scope'] == 'shared':
                    issue('plan.fixed_state_update', path+'/updates')
            for sid in step['creates']:
                state = states.get(sid)
                if (sid in ready or state is None or state['scope'] != step['scope']
                        or g is not None and g not in state['groups']
                        or state['source'] != {'kind': 'step', 'id': step['id']}):
                    issue('plan.creation_identity', path+'/creates')
                (available[g] if g is not None else shared).add(sid)
            if step['kind'] == 'measure':
                for mid in step['metricIds']:
                    metric = metrics.get(mid)
                    if metric:
                        required = {sid for sid in metric['stateIds'] if sid in states
                                    and (states[sid]['scope'] == 'shared' or g in states[sid]['groups'])}
                        if not required <= ready:
                            issue('plan.measurement_state_unavailable', path)
        bid = step['budgetId']
        if bid is not None:
            budget = budgets.get(bid)
            if (budget is None or step['scope'] != budget['scope']
                    or not set(step['groups']) <= set(budget['groups'])):
                issue('plan.budget_reference', path+'/budgetId')
            else:
                allocations.update((bid, g) for g in (step['groups'] if step['scope'] == 'arm' else ['shared']))
    for i, budget in enumerate(value['budgets']):
        if budget['unit'] != 'wall_seconds' and type(budget['cap']) is not int:
            issue('plan.budget_integer', f'/budgets/{i}/cap')
        if (budget['scope'] == 'shared' and budget['groups'] or budget['scope'] == 'arm' and not budget['groups']):
            issue('plan.budget_scope', f'/budgets/{i}')
        counts = [allocations[(budget['id'], g)] for g in (budget['groups'] if budget['scope'] == 'arm' else ['shared'])]
        if budget.get('allocation') == 'shared_preparation_total':
            positions = [j for j, step in enumerate(value['steps']) if step['budgetId'] == budget['id']]
            if (budget['scope'] != 'shared' or budget['unit'] != 'wall_seconds' or budget['matching'] != 'native'
                    or budget['cap'] <= 0 or not positions or positions != list(range(positions[0], positions[-1] + 1))
                    or any(value['steps'][j]['kind'] != 'prepare' for j in positions)
                    or any(step['scope'] != 'shared' for step in value['steps'][:positions[-1] + 1])):
                issue('plan.shared_preparation_budget', f'/budgets/{i}')
        elif any(n != 1 for n in counts): issue('plan.budget_allocation', f'/budgets/{i}')
        if budget['scope'] == 'arm' and budget['matching'] == 'equal' and set(budget['groups']) != set(GROUPS):
            issue('plan.unmatched_budget', f'/budgets/{i}/groups')
    if any(treatments[(f, g)] != 1 for f in ('A', 'B') for g in GROUPS):
        issue('plan.intervention_coverage', '/steps')
    if any(measurements[(m, g)] != 1 for m in metrics for g in GROUPS):
        issue('plan.measurement_coverage', '/steps')
    pairing = value['pairing']
    if not pairing['sharedStateIds'] or any(s not in states or states[s]['scope'] != 'shared' for s in pairing['sharedStateIds']):
        issue('plan.pairing_source', '/pairing/sharedStateIds')
    if evaluation_states.intersection(pairing['sharedStateIds']):
        issue('plan.evaluation_state_leakage', '/pairing/sharedStateIds')
    covered = set()
    for sid in pairing['cloneStepIds']:
        step = steps.get(sid)
        if (step is None or step['kind'] != 'clone' or step['scope'] != 'arm' or not step['creates']
                or not set(pairing['sharedStateIds']) <= set(step['reads'])):
            issue('plan.pairing_clone', '/pairing/cloneStepIds')
        else: covered.update(step['groups'])
    if covered != set(GROUPS): issue('plan.unpaired_groups', '/pairing/cloneStepIds')
    domains = {m['domain'] for m in value['metrics']}
    if not set(required_domains) <= domains: issue('plan.missing_measurement_domain', '/metrics')
    persisted = {s['id'] for s in value['states'] if s['persisted']}
    for i, metric in enumerate(value['metrics']):
        if not set(metric['stateIds']) <= set(states): issue('plan.metric_state', f'/metrics/{i}/stateIds')
        captures = metric.get('fitMemoryCaptures', [])
        if captures:
            captured_steps = {capture['stepId'] for capture in captures}
            fits = [step for step in value['steps'] if step['kind'] == 'fit' and step['scope'] == 'arm']
            shared_fits = {step['id'] for step in value['steps']
                           if step['kind'] == 'fit' and step['scope'] == 'shared'}
            required_fits = {step['id'] for step in fits}
            if captured_steps & shared_fits:
                required_fits |= shared_fits
            records = {capture['recordStateId'] for capture in captures}
            if (metric['domain'] != 'memory' or metric['direction'] != 'lower_better'
                    or len(captured_steps) != len(captures) or len(records) != len(captures)
                    or captured_steps != required_fits
                    or {group for step in fits for group in step['groups']} != set(GROUPS)
                    or not records <= set(metric['stateIds'])
                    or any(capture['recordStateId'] not in steps.get(capture['stepId'], {}).get('creates', [])
                           for capture in captures)):
                issue('plan.fit_memory_capture', f'/metrics/{i}/fitMemoryCaptures')
            elif any(not {capture['recordStateId'] for capture in captures
                           if (capture['stepId'] in shared_fits
                               or set(steps[capture['stepId']]['groups']) & set(step['groups']))} <= set(step['reads'])
                       for step in value['steps'] if metric['id'] in step['metricIds']):
                issue('plan.fit_memory_capture_read', f'/metrics/{i}/fitMemoryCaptures')
        elif metric['domain'] in ('storage', 'memory') and not persisted <= set(metric['stateIds']):
            issue('plan.incomplete_resource_accounting', f'/metrics/{i}/stateIds')
    if set(value['analysis']['metricIds']) != set(metrics): issue('plan.analysis_metrics', '/analysis/metricIds')
    contrasts = value['analysis']['contrasts']
    if {c['kind'] for c in contrasts} != set(CONTRASTS): issue('plan.contrast_identity', '/analysis/contrasts')
    for i, contrast in enumerate(contrasts):
        if contrast['weights'] != CONTRASTS[contrast['kind']]: issue('plan.contrast_weights', f'/analysis/contrasts/{i}')
    return issues


def bind_for_review(value, evidence_ids, *, context_digest, required_domains=(), count_unique_operations=False):
    """Freeze an unchecked proposal. Never expose a publication/approval flag."""
    if not isinstance(context_digest, str) or not re.fullmatch('[0-9a-f]{64}', context_digest):
        raise ValueError('Trusted complete research context digest required')
    issues = validate(value, evidence_ids, required_domains=required_domains,
                      count_unique_operations=count_unique_operations)
    if issues:
        raise ValueError('Invalid shared experiment proposal: '+','.join(sorted({i['code'] for i in issues})))
    bound = {'version': 2 if count_unique_operations else 1, 'contextDigest': context_digest,
            'proposal': deepcopy(value), 'proposalDigest': digest(value),
            'allowedEvidenceIds': sorted(set(evidence_ids)), 'requiredDomains': sorted(set(required_domains)),
            'status': 'awaiting_scientific_review', 'scientificApproval': False}
    return {**bound, 'bindingDigest': digest(bound)}


def validate_bound(bound, *, expected_digest):
    """Any later edit requires a new bound proposal and fresh scientific review."""
    expected = {'version', 'contextDigest', 'proposal', 'proposalDigest', 'allowedEvidenceIds', 'requiredDomains', 'status', 'scientificApproval', 'bindingDigest'}
    if (not isinstance(bound, dict) or set(bound) != expected or type(bound['version']) is not int
            or bound['version'] not in (1, 2) or bound['scientificApproval'] is not False
            or not isinstance(bound['contextDigest'], str) or not re.fullmatch('[0-9a-f]{64}', bound['contextDigest'])
            or bound['status'] != 'awaiting_scientific_review'):
        return False
    try:
        return (bound['bindingDigest'] == expected_digest
                and digest({k: v for k, v in bound.items() if k != 'bindingDigest'}) == expected_digest
                and digest(bound['proposal']) == bound['proposalDigest']
                and not validate(bound['proposal'], bound['allowedEvidenceIds'], required_domains=bound['requiredDomains'],
                                 count_unique_operations=bound['version'] == 2))
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
