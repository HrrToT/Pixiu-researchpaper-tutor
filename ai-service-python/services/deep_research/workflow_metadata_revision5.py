"""Separate bounded response storage from exact metadata content, for v5 only."""
from copy import deepcopy

from services.deep_research.workflow_metadata_revision3 import operation_feedback

RAW_RESPONSE_BYTES = 16384
CONTENT_BYTES = 8192
POLICY = (
    'baseline and training_data are reserved input handles; never declare them as components. '
    'baseline already denotes the complete prelude state. A distinct mutable copy needs its own '
    'nonreserved component ID and explicit later initializer. Component createAfter/disposeAfter '
    'reference actual phase IDs only, not state IDs. Keep every needed state and dependency. '
    'Return minified JSON; formatting never supplies missing scientific values.\n'
)


def over_capacity(raw, wire):
    from services.deep_research.execution_workflow_blueprint import packed
    return len(raw.encode('utf8')) > RAW_RESPONSE_BYTES or len(packed(wire).encode('utf8')) > CONTENT_BYTES


def field_feedback(wire):
    result = operation_feedback(wire)
    for i, row in enumerate(wire['componentRows']):
        if row[0] in ('baseline', 'training_data'):
            result['issues'].append({'code': 'wire.component.reserved_name',
                'path': f'/componentRows/{i}/0', 'actual': deepcopy(row[0]),
                'expected': 'nonreserved component ID; baseline/training_data are input handles, not components'})
    import json
    result['issues'].sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return result
