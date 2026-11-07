"""Read-only, versioned metadata diagnostics; no budget or lifecycle repair."""
from copy import deepcopy
import json

from services.deep_research.workflow_metadata_actions import decode, field_feedback as action_feedback
from services.deep_research.workflow_metadata_rows import PHASE_COLUMNS

POLICY = (
    'Select kind from the actual algorithm: fit performs optimization and requires a finite explicit '
    'budget {unit,perExecution}; optimizer_steps/epochs use nonnegative nonboolean integers, '
    'wall_seconds uses finite nonnegative numbers. Non-fit phases have budget:null. '
    'Do not relabel an optimization as setup merely to avoid its budget. Deterministic allocation '
    'or copying may be setup only when it performs no fitting. Preserve all required optimization '
    'and its whole-group accounting. A component allocated after a phase cannot be read or updated '
    'in that phase. Choose compatible initialization boundaries explicitly; never assume an instance exists.\n'
)


def _wire_path(path):
    parts = path.split('/')
    if len(parts) >= 4 and parts[1] == 'phases' and parts[3] in PHASE_COLUMNS:
        result = '/phaseRows/'+parts[2]+'/'+str(PHASE_COLUMNS.index(parts[3]))
        return result + ('/'+'/'.join(parts[4:]) if len(parts)>4 else '')
    if len(parts) >= 4 and parts[1] == 'components' and parts[3] == 'lifecycle':
        result = '/componentRows/'+parts[2]+'/2'
        if len(parts) > 4 and parts[4] in ('scope', 'createAfter', 'disposeAfter'):
            result += '/'+str(('scope', 'createAfter', 'disposeAfter').index(parts[4]))
            if len(parts) > 5: result += '/'+('/'.join(parts[5:]))
        return result
    return path


def _at(wire, path):
    value = wire
    for part in path.split('/')[1:]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return deepcopy(value)


def field_feedback(wire, aliases):
    result = action_feedback(wire)
    try: metadata = decode(wire)
    except (TypeError, ValueError, RecursionError, OverflowError):
        # Never construct a valid-looking proposal to diagnose a malformed one.
        return result
    from services.deep_research.workflow_metadata_repair import stable_feedback
    canonical = stable_feedback(metadata, aliases)
    result['codes'] = canonical['codes']
    for item in canonical['issues']:
        path = _wire_path(item['path'])
        issue = {**deepcopy(item), 'path': path}
        try: issue.update(actual=_at(wire, path), actualPresent=True)
        except (KeyError, IndexError, TypeError, ValueError): issue['actualPresent'] = False
        if item['code'] == 'timeline.phase.budget':
            issue['expected'] = ('fit needs {unit:optimizer_steps|epochs|wall_seconds,perExecution:finite >=0}; '
                'steps/epochs need an integer, not bool. Select kind from real computation; do not bypass fitting caps.')
        elif item['code'] == 'timeline.phase.nonfit_budget':
            issue['expected'] = 'null for non-fit; fitting requires explicit kind and finite budget'
        result['issues'].append(issue)
    phases = metadata['phases']; ids = [p['phaseId'] for p in phases]
    if all(isinstance(pid, str) for pid in ids) and len(set(ids)) == len(ids):
        positions = {pid:i for i,pid in enumerate(ids)}
        for component in metadata['components']:
            life = component.get('lifecycle', {}); after = life.get('createAfter')
            if not isinstance(after, list) or any(not isinstance(pid,str) or pid not in positions for pid in after): continue
            boundary = max((positions[pid] for pid in after), default=-1)
            cid = component['componentId']
            for i, phase in enumerate(phases):
                if i > boundary: continue
                reads = phase.get('reads'); updates = phase.get('updates')
                uses = ([('6/'+str(j), item) for j,item in enumerate(reads)
                         if isinstance(item,dict) and item.get('state')==cid] if isinstance(reads,list) else [])
                uses += ([('7/'+str(j), item) for j,item in enumerate(updates) if item==cid] if isinstance(updates,list) else [])
                for suffix, actual in uses:
                    path = f'/phaseRows/{i}/{suffix}'
                    result['issues'].append({'code':'wire.lifecycle.before_creation', 'path':path,
                        'actual':_at(wire, path), 'componentId':cid, 'createAfter':deepcopy(after),
                        'expected':'initialize the instance before this read/update; createAfter is after the named phase, not before it'})
    result['issues'].sort(key=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    return result
