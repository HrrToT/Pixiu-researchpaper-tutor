"""Target-specific initialization interfaces, bound to complete server context.

No evidence is projected. The full metadata and prior initializations remain
the authority for response checks and complete assembly.
"""
from copy import deepcopy

from services.deep_research.contracts import digest

POLICY = ('Scoped initialization interface; full context remains bound and validated by the server. '
          'operationRequirements constrain compatibility, not initialization actions. '
          'Never treat future operations as available inputs.\n')


def enabled(record):
    from services.deep_research.workflow_initialization_wire import enabled as wire
    from services.deep_research.workflow_premises import enabled as premises
    return (isinstance(record, dict)
            and type(record.get('workflowInitializationContextContractVersion')) is int
            and record['workflowInitializationContextContractVersion'] == 1
            and wire(record) and premises(record))


def _availability(meta, target, earlier):
    from services.deep_research.workflow_lifecycle import _creation_point
    phases = meta['phases']; phase_map = {p['phaseId']: (i, p) for i, p in enumerate(phases)}
    frames = [i for i, p in enumerate(phases) if p['scope'] == 'per_frame']
    start = frames[0] if frames else 0
    index = next(i for i, c in enumerate(meta['components']) if c == target)
    if [c['componentId'] for c in earlier] != [c['componentId'] for c in meta['components'][:index]]:
        raise ValueError('Initialization predecessors do not match the complete metadata')
    life = target['lifecycle']; point = _creation_point(life, phase_map, start)
    event = (point, int(life['scope'] == 'per_frame'), index + 1)
    groups = set(target['appliesTo'])
    def scope_ok(scope): return not (scope == 'per_frame' and life['scope'] == 'per_repeat')
    available_phases = [deepcopy(p) for i, p in enumerate(phases)
        if i < point and scope_ok(p['scope']) and groups <= set(p['groups'])]
    available_states = []
    for i, state in enumerate(earlier):
        source = state['lifecycle']; source_point = _creation_point(source, phase_map, start)
        source_event = (source_point, int(source['scope'] == 'per_frame'), i + 1)
        disposal = source['disposeAfter']
        if (source_event < event and scope_ok(source['scope']) and groups <= set(state['appliesTo'])
                and (disposal is None or point <= phase_map[disposal][0] + .25)):
            available_states.append(deepcopy(state))
    return available_phases, available_states


def project(context):
    """Derive a private interface; never mutate the context used for validation."""
    if not isinstance(context, dict) or set(context) not in (
            {'target', 'metadata', 'earlier'}, {'target', 'metadata', 'earlier', 'baselineInitialization'}):
        raise ValueError('Unsupported initialization context')
    meta = context['metadata']; target = context['target']
    if not isinstance(meta, dict) or not isinstance(meta.get('phases'), list) or not isinstance(meta.get('components'), list):
        raise ValueError('Complete initialization metadata is missing')
    header = {k: deepcopy(v) for k, v in meta.items() if k not in ('phases', 'components')}
    view = {'target': deepcopy(target), 'metadataHeader': header,
        'componentInterfaces': [{k: deepcopy(v) for k, v in c.items() if k != 'lifecycle'} for c in meta['components']]}
    if target == 'baseline':
        if context['earlier'] != [] or meta['baselineMode'] != 'train':
            raise ValueError('Baseline must precede the complete timeline')
        view['operationRequirements'] = [{k: deepcopy(p[k]) for k in ('groups', 'action', 'budget')}
            for p in meta['phases'] if p['kind'] in ('setup', 'fit')]
        view['earlier'] = []
    else:
        if target not in meta['components'] or 'baselineInitialization' not in context:
            raise ValueError('Initialization target is not in complete metadata')
        cid = target['componentId']
        available, predecessors = _availability(meta, target, context['earlier'])
        view['availablePhases'] = available
        view['earlier'] = predecessors
        view['baselineInitialization'] = deepcopy(context['baselineInitialization'])
        view['consumerInterfaces'] = [{k: deepcopy(p[k]) for k in
            ('phaseId', 'scope', 'kind', 'groups', 'sharing', 'reads', 'updates', 'action', 'budget')}
            for p in meta['phases'] if cid in p['updates']
            or any(r.get('state') == cid for r in p['reads'])]
    view['binding'] = {'metadataDigest': digest(meta), 'contextDigest': digest(context), 'phaseCount': len(meta['phases'])}
    return view
