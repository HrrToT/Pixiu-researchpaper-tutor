from copy import deepcopy
import json

import pytest

from services.deep_research import workflow_metadata_observation_boundary as boundary
from services.deep_research import workflow_metadata_result_refs as previous
from services.deep_research.workflow_metadata_repair import prompt_for
from services.deep_research.planning_transport import descriptor_for
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_metadata_result_refs import authored
from test_deep_research_workflow_metadata_bounded_schema import fixtures
from test_deep_research_workflow_metadata_ordered_integration import input_value
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers


def observation():
    value = fixtures()[3]
    for step in value['steps']:
        for read in step['reads']:
            if 'stepIndex' in read:
                stage = read.pop('outputStage')
                if stage == 'record': read['savedOutputId'] = read.pop('outputId')
    return value


def test_feedback_exposes_the_two_producers_without_fixing_or_dropping_results():
    value = observation()
    index, step = next((i,s) for i,s in enumerate(value['steps']) if s['kind']=='observe')
    step['outputs'].append('later_psnr')
    step['recording']['outputs'] = ['later_psnr']
    before = deepcopy(value)
    issue = next(i for i in boundary.field_feedback(value, {'E1':'owned'})['issues'] if i['code']=='steps.record_coverage')
    facts = issue['producerBoundary']
    assert facts['measurementOutputsPath'] == f'/steps/{index}/outputs'
    assert facts['measurementOutputs'] == step['outputs']
    assert facts['unselectedMeasurementOutputs'] == ['later_psnr']
    assert facts['recordingOutputs'] == ['later_psnr']
    assert facts['undeclaredInputOutputs'] == []
    assert value == before
    with pytest.raises(ValueError): boundary.decode(value)


def test_unknown_record_input_is_reported_without_inventing_a_selector():
    value = observation()
    step = next(s for s in value['steps'] if s['kind']=='observe')
    step['recording']['inputs'].append({'outputId':'not_measured','selector':'chosen'})
    before = deepcopy(value)
    issue = next(i for i in boundary.field_feedback(value, {'E1':'owned'})['issues'] if i['code']=='steps.record_coverage')
    assert issue['producerBoundary']['undeclaredInputOutputs'] == ['not_measured']
    assert value == before


def test_same_name_between_measurement_and_record_is_not_automatically_an_error():
    value = observation()
    step = next(s for s in value['steps'] if s['kind']=='observe')
    step['recording']['outputs'] = deepcopy(step['outputs'])
    assert not any(i['code']=='steps.record_coverage' for i in boundary.field_feedback(value, {'E1':'owned'})['issues'])
    assert boundary.decode(value) == previous.decode(value)


def test_new_prompt_and_feedback_are_versioned_but_schema_and_decoding_remain_identical():
    value = authored()
    assert boundary.decode(value) == previous.decode(value)
    assert boundary.descriptor()['schema'] == previous.descriptor()['schema']
    data = json.dumps({'evidence':'exact original'})
    feedback = boundary.field_feedback(value, {'E1':'owned'})
    assert prompt_for(data,value,feedback,version=27) == previous.revision_prompt(data,value,feedback)
    new = prompt_for(data,value,feedback,version=28)
    assert 'TWO ordered operations' in new and input_value(new)['invalidMetadata']==value
    assert input_value(boundary.generation_prompt(data,{}))['authoritativeInput']==json.loads(data)


def test_version28_uses_new_descriptor_and_one_durable_revision():
    good = authored(); bad = deepcopy(good)
    bad['steps'][2]['reads'] = [{'stepIndex':0,'outputId':'missing','selector':'all'}]
    record, _, invoke, run = setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    record.update(workflowMetadataRepairContractVersion=28,workflowInitializationOutputContractVersion=1)
    assert descriptor_for(record, 'plan_workflow_meta')['name']=='metadata_observation_boundary_v1'
    saved=run()
    assert saved['status']==saved['metadataRepair']['status']=='ready'
    assert saved['metadataRepair']['version']==28
    assert 'TWO ordered operations' in saved['metadataRepair']['request']['prompt']
    assert saved['units']['metadata']['response']==response(bad)
    assert run()==saved and invoke.call_count==5


def test_version28_does_not_repeat_an_unsuccessful_revision():
    bad=authored();bad['steps'][2]['reads']=[{'stepIndex':0,'outputId':'missing','selector':'all'}]
    record, _, invoke, run=setup_repair([response(bad),response(bad)])
    record.update(workflowMetadataRepairContractVersion=28,workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2
