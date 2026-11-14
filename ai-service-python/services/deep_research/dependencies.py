"""Durable dependency frontiers; coverage readiness is not a scientific verdict."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError, digest


def enabled(record):
    return type(record.get('dependencyContractVersion')) is int and record['dependencyContractVersion'] == 1


def initialize(plan, revision=0):
    roots = [item['itemId'] for item in plan if not item.get('dependencies')]
    return {'version': 1, 'planRevision': revision, 'wave': 0, 'active': roots[:2],
            'settled': [], 'satisfied': [], 'requeryCount': 0, 'pending': None, 'lastTransition': None}


def journal(record):
    domain = record.get('state') or {}
    value = domain.get('dependencyExecution')
    known = {item['itemId'] for item in domain.get('plan', [])}
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
            or value.get('planRevision') != domain.get('planRevision', 0)
            or type(value.get('wave')) is not int or value['wave'] < 0
            or type(value.get('requeryCount')) is not int or value['requeryCount'] < 0):
        raise DeepResearchError('invalid_dependency_state', '保存的计划依赖状态无效，不能派发。')
    for key in ('active', 'settled', 'satisfied'):
        values = value.get(key)
        if (not isinstance(values, list) or any(not isinstance(v, str) or v not in known for v in values)
                or len(values) != len(set(values)) or (key == 'active' and len(values) > 2)):
            raise DeepResearchError('invalid_dependency_state', '保存的依赖节点身份无效，不能派发。')
    if not set(value['satisfied']).issubset(value['settled']):
        raise DeepResearchError('invalid_dependency_state', '依赖完成状态不一致。')
    for key in ('pending', 'lastTransition'):
        transition = value.get(key)
        if transition is None:
            continue
        if (not isinstance(transition, dict) or set(transition) != {'id', 'active', 'fromWave'}
                or type(transition.get('fromWave')) is not int or transition['fromWave'] < 0
                or not isinstance(transition.get('active'), list) or not 1 <= len(transition['active']) <= 2
                or any(not isinstance(v, str) or v not in known for v in transition['active'])
                or len(transition['active']) != len(set(transition['active']))
                or transition.get('id') != digest({'planRevision': value['planRevision'],
                    'wave': transition['fromWave'], 'next': transition['active']})
                or transition['fromWave'] != value['wave'] - (key == 'lastTransition')):
            raise DeepResearchError('invalid_dependency_state', '保存的依赖批次迁移无效。')
    return value


def scoped_record(record):
    if not enabled(record):
        return record
    active = set(journal(record)['active'])
    domain = record.get('state') or {}
    plan = [item for item in domain.get('plan', []) if item['itemId'] in active]
    obligations = {o['obligationId'] for item in plan for o in item['obligations']}
    return {**record, 'state': {**domain, 'plan': plan,
        'gaps': [g for g in domain.get('gaps', []) if g.get('obligationId') in obligations],
        'coverage': [c for c in domain.get('coverage', []) if c.get('obligationId') in obligations]}}


def scoped_updater(update):
    """Keep the full plan/earlier gaps in storage while nodes see one frontier."""
    def scoped(run_id, mutate, **kwargs):
        def merge(current):
            if not enabled(current):
                return mutate(current)
            before = current.get('state') or {}
            view = scoped_record(current)
            active_ids = {item['itemId'] for item in view['state']['plan']}
            active_obligations = {o['obligationId'] for item in view['state']['plan'] for o in item['obligations']}
            proposed = mutate(view)
            domain = dict(proposed.get('state') or {})
            active = {item['itemId']: item for item in domain.get('plan', [])}
            if not set(active).issubset(active_ids):
                raise DeepResearchError('invalid_dependency_state', '活动计划不能增加其他节点。')
            domain['plan'] = [active.get(item['itemId'], item) for item in before['plan']]
            for key in ('gaps', 'coverage'):
                domain[key] = [row for row in before.get(key, []) if row.get('obligationId') not in active_obligations]
                domain[key].extend((proposed.get('state') or {}).get(key, []))
            return {**proposed, 'state': domain}
        return scoped_record(update(run_id, merge, **kwargs))
    return scoped


def finish_assessment(state, output, update):
    record = update(state['run_id'], lambda r: r, expected_revision=None)
    if not enabled(record) or output.get('error_code'):
        return output
    current = deepcopy(journal(record))
    if current.get('pending'):
        return {**output, 'dependency_transition': current['pending']['id']}
    if output.get('gaps') and output.get('extraction_pending') and not output.get('budget_exhausted'):
        return output
    # Keep the current frontier while its bounded targeted investigation runs.
    if output.get('gaps') and not output.get('stop_reason') and output.get('requery_queries'):
        return output
    plan = record['state']['plan']
    by_id = {item['itemId']: item for item in plan}
    current['settled'] = list(dict.fromkeys([*current['settled'], *current['active']]))
    current['satisfied'] = list(dict.fromkeys([*current['satisfied'],
        *[identity for identity in current['active'] if by_id[identity].get('status') == 'completed']]))
    current['requeryCount'] = output.get('requery_count', state.get('requery_count', 0))
    ready = [item['itemId'] for item in plan if item['itemId'] not in current['settled']
             and set(item.get('dependencies', [])).issubset(current['satisfied'])][:2]
    stopped = output.get('budget_exhausted') or state.get('budget_exhausted')
    if ready and not stopped:
        token = digest({'planRevision': current['planRevision'], 'wave': current['wave'], 'next': ready})
        current['pending'] = {'id': token, 'active': ready, 'fromWave': current['wave']}
        update(state['run_id'], lambda r: {**r, 'state': {**r['state'], 'dependencyExecution': current}}, expected_revision=None)
        return {**output, 'dependency_transition': token}
    # A failed prerequisite must not look like an investigated descendant.
    gaps = list(record['state'].get('gaps', []))
    for item in plan:
        if item['itemId'] in current['settled']:
            continue
        for obligation in item['obligations']:
            gaps.append({'obligationId': obligation['obligationId'], 'question': obligation['question'],
                         'checked': False, 'missingEvidence': '预算不足，尚未开始' if stopped else '依赖的研究问题尚未完成'})
    update(state['run_id'], lambda r: {**r, 'state': {**r['state'], 'dependencyExecution': current,
        'gaps': gaps}}, expected_revision=None)
    return {**output, 'gaps': gaps, 'dependency_transition': ''}


def advance_frontier(state, update):
    record = update(state['run_id'], lambda r: r, expected_revision=None)
    current = deepcopy(journal(record))
    token = state.get('dependency_transition')
    pending = current.get('pending')
    if pending and pending.get('id') == token and pending.get('fromWave') == current['wave']:
        current['active'] = pending['active']
        current['wave'] += 1
        current['lastTransition'] = pending
        current['pending'] = None
        update(state['run_id'], lambda r: {**r, 'state': {**r['state'], 'dependencyExecution': current}}, expected_revision=None)
    elif not current.get('lastTransition') or current['lastTransition'].get('id') != token:
        raise DeepResearchError('invalid_dependency_state', '依赖检查点与已保存的批次不一致。')
    return {'dependency_transition': '', 'dependency_wave': current['wave'], 'extraction_pending': False,
            'requery_count': current['requeryCount'], 'requery_queries': [], 'gaps': [],
            'stop_reason': '', 'prev_source_count': 0, 'prev_assessment_evidence_digest': ''}
