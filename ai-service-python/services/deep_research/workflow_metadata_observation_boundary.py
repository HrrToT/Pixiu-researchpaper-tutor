"""Explain observation stages without changing or repairing authored values."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_result_refs as previous

decode = previous.decode
complete_scaffolding = previous.complete_scaffolding
POLICY = previous.POLICY + (
    'Observe has TWO ordered operations: measurement produces step.outputs; recording '
    'reads those through recording.inputs and produces recording.outputs. step.outputs '
    'contains ONLY results already produced by measurement, not later recording results. '
    'Example: if measurement renders images and recording computes PSNR, step.outputs '
    'declares images; recording.inputs selects images; recording.outputs declares PSNR. '
    'If measurement computes PSNR too, declare and select it there instead. Preserve every '
    'required computation and result in its actual producing operation; never drop a metric '
    'or invent a selector to pass coverage. Each measurement output needs an explicit '
    'recording.inputs selection. This example supplies no scientific or dataset choices.\n'
)


def descriptor():
    result = previous.descriptor()
    result['name'] = 'metadata_observation_boundary_v1'
    return result


def field_feedback(value, aliases):
    result = previous.field_feedback(value, aliases)
    for issue in result['issues']:
        if issue['code'] != 'steps.record_coverage':
            continue
        parts = issue['path'].split('/')
        step = value['steps'][int(parts[2])]
        outputs = step['outputs']
        inputs = step['recording']['inputs']
        selected = [item['outputId'] for item in inputs]
        issue['producerBoundary'] = {
            'measurementOutputsPath': f'/steps/{parts[2]}/outputs',
            'measurementOutputs': deepcopy(outputs),
            'recordingOutputs': deepcopy(step['recording']['outputs']),
            'unselectedMeasurementOutputs': [name for name in outputs if name not in selected],
            'undeclaredInputOutputs': [name for name in selected if name not in outputs],
        }
        issue['expected'] = (
            'Choose the actual producing operation for each result. Measurement precedes '
            'recording: step.outputs must not include a result only computed by recording. '
            'Select every measurement output in recording.inputs with an authored selector; '
            'declare recording results in recording.outputs. Preserve all needed computations '
            'and results; do not blindly add an input or delete a metric. No automatic repair.'
        )
    return result


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return POLICY + COUNT_POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return POLICY + COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})
