"""Read-only metadata feedback. Never rename IDs or repair proposed values."""
from copy import deepcopy

from services.deep_research.workflow_units import META, unit_errors
from services.deep_research.workflow_lifecycle import lifecycle_issues
from services.deep_research.workflow_lifecycle_units import timeline_spec


def feedback(metadata, aliases):
    """Explain emitted references even if malformed lifecycle types stop a DAG check.

    This is not a second validator, an approval, or an allocation of source
    permissions. The existing unit and full-workflow validators remain required.
    """
    codes = unit_errors(metadata, aliases, node=META, version=7, metadata_rows=True)
    if not isinstance(metadata, dict):
        return {'codes': codes, 'issues': [], 'declaredPhaseIds': [],
                'declaredComponentIds': [], 'scientificApproval': False}
    phases = metadata.get('phases')
    components = metadata.get('components')
    phases = phases if isinstance(phases, list) else []
    components = components if isinstance(components, list) else []
    phase_ids = [p['phaseId'] for p in phases if isinstance(p, dict) and isinstance(p.get('phaseId'), str)]
    component_ids = [c['componentId'] for c in components
                     if isinstance(c, dict) and isinstance(c.get('componentId'), str)]
    outputs_by_phase = {p['phaseId']: p.get('outputs', []) for p in phases
                        if isinstance(p, dict) and isinstance(p.get('phaseId'), str)}
    issues = []

    def add(code, path, expected, actual):
        issues.append({'code': code, 'path': path, 'expected': expected, 'actual': deepcopy(actual)})

    # Retain the original checks' exact paths/codes as well as local explanations.
    try:
        deferred = {'timeline.component.unused', 'timeline.record.evaluation_missing'}
        for issue in lifecycle_issues(timeline_spec(metadata)):
            if issue['code'] not in deferred:
                issues.append({**issue, 'path': issue['path'].replace('/componentInitializations/', '/components/')})
    except (KeyError, TypeError, ValueError, RecursionError, OverflowError):
        # The canonical field error already rejects the malformed proposal.
        # Do not synthesize missing fields to run deeper checks.
        pass

    def phase_refs(value, path):
        if not isinstance(value, list):
            add('metadata.phase_refs.type', path, 'array of exact declared phase IDs; [] before timeline', value)
            return
        for j, ref in enumerate(value):
            if not isinstance(ref, str) or ref not in phase_ids:
                add('metadata.phase_refs.unknown', path+'/'+str(j), 'one exact declared phase ID', ref)

    for i, component in enumerate(components):
        if not isinstance(component, dict) or not isinstance(component.get('lifecycle'), dict):
            continue
        life = component['lifecycle']; path = '/components/'+str(i)+'/lifecycle'
        phase_refs(life.get('createAfter'), path+'/createAfter')
        if life.get('disposeAfter') is not None and life['disposeAfter'] not in phase_ids:
            add('metadata.disposal.unknown', path+'/disposeAfter', 'exact declared phase ID or null', life['disposeAfter'])
    for i, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        path = '/phases/'+str(i)
        phase_refs(phase.get('after'), path+'/after')
        reads = phase.get('reads')
        if isinstance(reads, list):
            for j, item in enumerate(reads):
                read_path = path+'/reads/'+str(j)
                if isinstance(item, dict) and set(item) == {'state', 'selector'}:
                    if item['state'] not in component_ids + ['baseline', 'training_data']:
                        add('metadata.read.unknown_state', read_path+'/state',
                            'declared state; calculated results use phaseId/outputId references', item['state'])
                elif isinstance(item, dict) and set(item) == {'phaseId', 'outputId', 'selector'}:
                    pid = item['phaseId']
                    if not isinstance(pid, str) or pid not in outputs_by_phase:
                        add('metadata.read.unknown_phase', read_path+'/phaseId',
                            'one exact declared phase ID', pid)
                    elif not isinstance(outputs_by_phase[pid], list) or item['outputId'] not in outputs_by_phase[pid]:
                        add('metadata.read.unknown_output', read_path+'/outputId',
                            'one exact output ID declared by the referenced phase', item['outputId'])
                else:
                    add('metadata.read.fields', read_path,
                        '{state,selector} or {phaseId,outputId,selector}', item)
        updates = phase.get('updates')
        if phase.get('kind') in ('evaluate', 'record') and updates:
            add('metadata.readonly.updates', path+'/updates',
                '[]; calculated metrics are phase outputs, not state updates', updates)
        if isinstance(updates, list):
            for j, target in enumerate(updates):
                if target not in component_ids + ['baseline']:
                    add('metadata.update.unknown', path+'/updates/'+str(j),
                        'declared mutable state; new result values belong in outputs', target)
    return {'codes': list(codes), 'issues': issues, 'declaredPhaseIds': phase_ids,
            'declaredComponentIds': component_ids, 'scientificApproval': False}
