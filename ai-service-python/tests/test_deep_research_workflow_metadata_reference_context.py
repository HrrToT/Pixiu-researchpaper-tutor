from copy import deepcopy
import json

import pytest

from services.deep_research import workflow_metadata_reference_context as refs
from services.deep_research import workflow_metadata_compact_transport as previous
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def unknown_read():
    value = wire_value()
    value['steps'][3]['reads'] = [{'state': 'metrics', 'selector': 'all'}]
    return value


def unknown_issue(result):
    return next(i for i in result['issues'] if i['code'] == 'metadata.read.unknown_state')


def test_all_authored_producers_retained_with_cross_arm_and_future_blockers():
    value = unknown_read(); before = deepcopy(value)
    result = refs.field_feedback(value, {'E1': 'owned'}); issue = unknown_issue(result)
    assert issue['path'] == '/steps/3/reads/0/state' and issue['actual'] == 'metrics'
    assert issue['consumerGroups'] == ['1']
    assert [(x['stepIndex'], x['blockedBy']) for x in issue['outputMatches']] == [(2, ['groups']), (3, ['not_earlier'])]
    assert all(x['outputStage'] == 'operation' and x['outputId'] == 'metrics' for x in issue['outputMatches'])
    assert 'stepIndex/outputStage/outputId/selector' in issue['expected'] and 'phaseId' not in issue['expected']
    assert value == before and not result['scientificApproval']
    assert refs.decode is previous.decode and refs.descriptor() == previous.descriptor()


def test_scope_blocks_existing_frame_output_and_does_not_suggest_new_state():
    value = unknown_read(); value['steps'][3]['scope'] = 'per_repeat'
    issue = unknown_issue(refs.field_feedback(value, {'E1': 'owned'}))
    assert 'scope' in next(x for x in issue['outputMatches'] if x['stepIndex'] == 2)['blockedBy']
    assert 'not_earlier' in next(x for x in issue['outputMatches'] if x['stepIndex'] == 3)['blockedBy']
    assert 'replacement' not in issue and 'selectedProducer' not in issue


def test_unknown_name_without_any_producer_is_not_guessed():
    value = unknown_read(); value['steps'][3]['reads'][0]['state'] = 'nonexistent'
    issue = unknown_issue(refs.field_feedback(value, {'E1': 'owned'}))
    assert issue['outputMatches'] == [] and issue['actual'] == 'nonexistent'


def test_observe_measurement_and_record_are_distinct_producers():
    from test_deep_research_workflow_metadata_steps import observations
    from test_deep_research_workflow_metadata_single_group import authored
    from services.deep_research.workflow_metadata_scope_position import FIELD
    value = authored(observations)
    for component in value['components']:
        life = component['lifecycle']; life[FIELD] = life.pop('createBefore')
    for step in value['steps']:
        if step['kind'] == 'evaluate': step['group'] = step.pop('groups')[0]
    observer = next((i,s) for i,s in enumerate(value['steps']) if s['kind'] == 'observe')
    i, source = observer
    source['outputs'] = ['ambiguous']; source['recording']['outputs'] = ['ambiguous']
    source['recording']['inputs'] = [{'outputId': 'ambiguous', 'selector': 'all'}]
    value['steps'][-1]['reads'] = [{'state': 'ambiguous', 'selector': 'all'}]
    issue = unknown_issue(refs.field_feedback(value, {'E1': 'owned'}))
    assert {x['outputStage'] for x in issue['outputMatches'] if x['stepIndex'] == i} == {'measurement', 'record'}


def test_full_revision_assembly_resume_and_original_input_preservation():
    good = wire_value(); bad = unknown_read()
    r, original, invoke, run = setup_repair([response(bad), response(good), *map(response, explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=23, workflowInitializationOutputContractVersion=1)
    saved = run(); repair = saved['metadataRepair']
    assert saved['status'] == repair['status'] == 'ready'
    data = input_value(repair['request']['prompt'])
    assert data['invalidMetadata'] == bad
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert unknown_issue(data['fieldFeedback'])['outputMatches']
    assert saved['units']['metadata']['response'] == response(bad)
    assert run() == saved and invoke.call_count == 5


def test_producer_context_is_not_a_runtime_correction_or_extra_retry():
    bad = unknown_read()
    r, _, invoke, run = setup_repair([response(bad), response(bad)])
    r['workflowMetadataRepairContractVersion'] = 23
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
    assert r['state']['executionWorkflowBlueprint']['metadataRepair']['errors']
