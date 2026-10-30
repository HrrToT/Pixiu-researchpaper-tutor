"""Point at complete wire-format errors without decoding or fixing bad leaves."""
from copy import deepcopy
import json

from services.deep_research.workflow_metadata_rows import COMMON


def complete_scaffolding(wire):
    """Known outer columns only; leaf correctness is explicitly NOT implied."""
    if (not isinstance(wire, dict) or set(wire) != {*COMMON, 'componentRows', 'phaseRows'}
            or not isinstance(wire['componentRows'], list) or not isinstance(wire['phaseRows'], list)
            or not 1 <= len(wire['phaseRows']) <= 128 or len(wire['componentRows']) > 128):
        return False
    try: json.dumps(wire, allow_nan=False)
    except (ValueError, TypeError, RecursionError, OverflowError): return False
    return (all(isinstance(row, list) and len(row) == 3 for row in wire['componentRows'])
            and all(isinstance(row, list) and len(row) == 11 for row in wire['phaseRows']))


def feedback(wire):
    if not complete_scaffolding(wire): raise ValueError('Incomplete metadata row scaffolding')
    phase_ids = [row[0] for row in wire['phaseRows'] if isinstance(row[0], str)]
    component_ids = [row[0] for row in wire['componentRows'] if isinstance(row[0], str)]
    issues = []
    def add(code, path, expected, actual):
        issues.append({'code': code, 'path': path, 'expected': expected, 'actual': deepcopy(actual)})
    def refs(value, path):
        if not isinstance(value, list):
            add('wire.phase_refs.type', path, 'array of exact declared phase IDs; [] before timeline', value)
        else:
            for j, item in enumerate(value):
                if not isinstance(item, str) or item not in phase_ids:
                    add('wire.phase_refs.unknown', path+'/'+str(j), 'one exact declared phase ID', item)
    for i, row in enumerate(wire['componentRows']):
        life = row[2]; path = '/componentRows/'+str(i)+'/2'
        if not isinstance(life, list) or len(life) != 3:
            add('wire.lifecycle.columns', path, '[scope,createAfter,disposeAfter]', life); continue
        refs(life[1], path+'/1')
        if life[2] is not None and life[2] not in phase_ids:
            add('wire.disposal.unknown', path+'/2', 'one exact declared phase ID or null', life[2])
    for i, row in enumerate(wire['phaseRows']):
        path = '/phaseRows/'+str(i); refs(row[5], path+'/5')
        if not isinstance(row[6], list):
            add('wire.reads.type', path+'/6', 'array of read rows', row[6])
        else:
            for j, item in enumerate(row[6]):
                read_path = path+'/6/'+str(j)
                if not isinstance(item, list) or len(item) not in (2, 3):
                    add('wire.read.columns', read_path, '[state,selector] or [phaseId,outputId,selector]', item)
                elif len(item) == 2 and item[0] not in component_ids + ['baseline', 'training_data']:
                    add('wire.read.state', read_path+'/0', 'declared state or explicit phase-output read row', item[0])
                elif len(item) == 3 and item[0] not in phase_ids:
                    add('wire.read.phase', read_path+'/0', 'one exact declared phase ID', item[0])
        if row[2] in ('evaluate', 'record') and row[7]:
            add('wire.readonly.updates', path+'/7', '[]; metrics are outputs, not mutable state', row[7])
        if isinstance(row[7], list):
            for j, target in enumerate(row[7]):
                if target not in component_ids + ['baseline']:
                    add('wire.update.state', path+'/7/'+str(j), 'declared mutable state; results belong in outputs', target)
    issues.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return {'issues': issues, 'declaredPhaseIds': phase_ids, 'declaredComponentIds': component_ids,
            'scientificApproval': False, 'decodedProposal': False}
