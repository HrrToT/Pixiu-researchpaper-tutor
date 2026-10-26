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


def qualified_field_feedback(value, aliases):
    """Show both explicitly authored blocks of the selected producer; select neither."""
    result = field_feedback(value, aliases)
    for issue in result['issues']:
        if issue['code'] not in ('result_ref.output', 'result_ref.saved_source'):
            continue
        parts = issue['path'].split('/')
        read = value['steps'][int(parts[2])]['reads'][int(parts[4])]
        index = read['stepIndex']
        producer = value['steps'][index]
        blocks = {'stepIndex': index, 'outputId': deepcopy(producer.get('outputs'))}
        if producer.get('kind') == 'observe':
            recording = producer.get('recording')
            blocks['savedOutputId'] = deepcopy(
                recording.get('outputs') if isinstance(recording, dict) else None)
        issue['declaredProducer'] = blocks
        issue.pop('declaredOutputs', None)  # The same authored list is present in declaredProducer.
        issue['expected'] = (
            'Choose field+ID: outputId=primitive/measurement, savedOutputId=observe.recording. '
            'Blocks are declarations, not selections or approval. Preserve required results/operations.'
        )
    return result


def complete_field_feedback(value, aliases):
    """Include independently invalid envelope leaves before timeline diagnostics."""
    result = qualified_field_feedback(value, aliases)
    issues = []
    def add(code, path, actual, expected):
        issues.append({'code': code, 'path': path, 'actual': deepcopy(actual), 'expected': expected})
    refs = value.get('sourceRefs')
    allowed = sorted(aliases)
    if not isinstance(refs, list) or len(refs) > 20:
        add('unit.sourceRefs', '/sourceRefs', refs, 'at most20 distinct evidence aliases from allowedSourceRefs; not paper IDs')
    if isinstance(refs, list):
        for index, ref in enumerate(refs):
            if not isinstance(ref, str) or ref not in aliases or ref in refs[:index]:
                add('unit.sourceRefs', f'/sourceRefs/{index}', ref, 'one distinct evidence alias from allowedSourceRefs; not a paper ID')
    if any(issue['code']=='unit.sourceRefs' for issue in issues):
        result['allowedSourceRefs'] = allowed
    gaps = value.get('unresolved')
    if not isinstance(gaps, list) or len(gaps) > 8:
        add('unit.unresolved', '/unresolved', gaps, 'at most8 explicit nonempty gap strings')
    if isinstance(gaps, list):
        for index, gap in enumerate(gaps):
            if not isinstance(gap, str) or not gap.strip():
                add('unit.unresolved', f'/unresolved/{index}', gap, 'nonempty gap string; never fabricate a resolution')
    for field, choices in (('baselineMode', ['train','existing']),
                           ('replicationMode', ['retrained_per_seed','fixed_checkpoint'])):
        if value.get(field) not in choices:
            add('unit.'+field, '/'+field, value.get(field), choices)
    result['issues'] = issues + result['issues']
    return result


COMPACT_POLICY = POLICY.replace(
    'Complete concise English JSON.',
    'Return ONE complete minified English JSON object: no indentation, line breaks, '
    'fences or commentary. Preserve all required fields, operations, results and evidence.')
QUALIFIED_POLICY = COMPACT_POLICY[:COMPACT_POLICY.index('Example: if measurement')] + (
    'Keep every required computation and result in its actual producing operation. '
    'Select every measurement output explicitly; never invent selectors or drop metrics.\n')


def generation_prompt(source_data, context, *, compact=False, qualified=False):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return (QUALIFIED_POLICY if qualified else COMPACT_POLICY if compact else POLICY) + COUNT_POLICY + input_text({'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback, *, compact=False, qualified=False):
    from services.deep_research.workflow_metadata_input import input_text
    from services.deep_research.workflow_metadata_fit_budget import COUNT_POLICY
    return (QUALIFIED_POLICY if qualified else COMPACT_POLICY if compact else POLICY) + COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def compact_generation_prompt(source_data, context):
    return generation_prompt(source_data, context, compact=True)


def compact_revision_prompt(source_data, value, feedback):
    return revision_prompt(source_data, value, feedback, compact=True)


def qualified_generation_prompt(source_data, context):
    return generation_prompt(source_data, context, qualified=True)


def qualified_revision_prompt(source_data, value, feedback):
    return revision_prompt(source_data, value, feedback, qualified=True)


SOURCE_POLICY = ('sourceRefs selects supported evidence aliases from allowedSourceRefs, '
                 'never paper IDs. This list is syntax permission, not evidence of support; '
                 'do not select aliases automatically.\n')


def complete_generation_prompt(source_data, context):
    return SOURCE_POLICY + qualified_generation_prompt(source_data, context)


def complete_revision_prompt(source_data, value, feedback):
    return SOURCE_POLICY + qualified_revision_prompt(source_data, value, feedback)
