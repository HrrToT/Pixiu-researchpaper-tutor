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


@pytest.mark.parametrize('version', [28, 29, 30])
def test_new_versions_use_new_descriptor_and_one_durable_revision(version):
    good = authored(); bad = deepcopy(good)
    bad['steps'][2]['reads'] = [{'stepIndex':0,'outputId':'missing','selector':'all'}]
    record, _, invoke, run = setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    record.update(workflowMetadataRepairContractVersion=version,workflowInitializationOutputContractVersion=1)
    assert descriptor_for(record, 'plan_workflow_meta')['name']=='metadata_observation_boundary_v1'
    saved=run()
    assert saved['status']==saved['metadataRepair']['status']=='ready'
    assert saved['metadataRepair']['version']==version
    assert 'TWO ordered operations' in saved['metadataRepair']['request']['prompt']
    if version == 30:
        issue=input_value(saved['metadataRepair']['request']['prompt'])['fieldFeedback']['issues'][0]
        assert issue['declaredProducer']['stepIndex']==0
    assert saved['units']['metadata']['response']==response(bad)
    assert run()==saved and invoke.call_count==5


@pytest.mark.parametrize('version', [28, 29, 30])
def test_new_versions_do_not_repeat_an_unsuccessful_revision(version):
    bad=authored();bad['steps'][2]['reads']=[{'stepIndex':0,'outputId':'missing','selector':'all'}]
    record, _, invoke, run=setup_repair([response(bad),response(bad)])
    record.update(workflowMetadataRepairContractVersion=version,workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2


def test_compact_prompt_is_only_for_new_version_and_preserves_input_and_schema():
    data=json.dumps({'evidence':'source line\nnext line','value':'minified is quoted data'})
    value=authored();feedback=boundary.field_feedback(value, {'E1':'owned'})
    old=prompt_for(data,value,feedback,version=28)
    new=prompt_for(data,value,feedback,version=29)
    assert old==boundary.revision_prompt(data,value,feedback)
    assert 'ONE complete minified' in new and new!=old
    assert input_value(old)==input_value(new)
    qualified=prompt_for(data,value,feedback,version=30)
    assert input_value(qualified)==input_value(new)
    assert 'Example: if measurement' not in qualified
    assert 'Keep every required computation and result' in qualified
    assert input_value(boundary.qualified_generation_prompt(data,{}))==input_value(boundary.generation_prompt(data,{}))
    assert input_value(boundary.compact_generation_prompt(data,{}))==input_value(boundary.generation_prompt(data,{}))


@pytest.mark.parametrize('version', [28, 29, 30])
def test_truncated_response_cannot_enter_repair_or_be_retried(version):
    truncated=response(authored());truncated['finishReason']='length'
    record, _, invoke, run=setup_repair([truncated])
    record.update(workflowMetadataRepairContractVersion=version,workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==1
    assert 'metadataRepair' not in record['state']['executionWorkflowBlueprint']


@pytest.mark.parametrize('field,output', [('outputId','psnr'),('savedOutputId','image')])
def test_wrong_result_field_lists_both_selected_producer_blocks_without_changing_it(field,output):
    value={'steps':[
        {'kind':'observe','scope':'per_frame','group':'1','outputs':['image'],
         'recording':{'outputs':['psnr']},'reads':[]},
        {'kind':'record','reads':[{'stepIndex':0,field:output,'selector':'chosen_slice'}]}]}
    before=deepcopy(value)
    old=boundary.field_feedback(value,{})
    feedback=boundary.qualified_field_feedback(value,{})
    assert 'declaredProducer' not in old['issues'][0]
    assert feedback['issues'][0]['declaredProducer']=={
        'stepIndex':0,'outputId':['image'],'savedOutputId':['psnr']}
    assert value==before and not feedback['scientificApproval']
    with pytest.raises(ValueError):boundary.decode(value)


def test_feedback_never_looks_up_or_selects_a_different_producer():
    value={'steps':[
        {'kind':'setup','outputs':['selected'],'reads':[]},
        {'kind':'setup','outputs':['other'],'reads':[]},
        {'kind':'record','reads':[{'stepIndex':0,'savedOutputId':'other','selector':'all'}]}]}
    issue=boundary.qualified_field_feedback(value,{})['issues'][0]
    assert issue['code']=='result_ref.saved_source'
    assert issue['declaredProducer']=={'stepIndex':0,'outputId':['selected']}
    assert issue['actual']=='other'


def test_feedback_keeps_same_named_blocks_and_malformed_saved_block_explicit():
    value={'steps':[
        {'kind':'observe','outputs':['same'],'recording':{'outputs':['same']},'reads':[]},
        {'kind':'record','reads':[{'stepIndex':0,'outputId':'missing','selector':'all'}]}]}
    blocks=boundary.qualified_field_feedback(value,{})['issues'][0]['declaredProducer']
    assert blocks=={'stepIndex':0,'outputId':['same'],'savedOutputId':['same']}
    value['steps'][0]['recording']=None
    blocks=boundary.qualified_field_feedback(value,{})['issues'][0]['declaredProducer']
    assert blocks['savedOutputId'] is None


def test_result_block_feedback_does_not_remove_cross_arm_checks():
    value=authored();value['steps'][2]['reads']=[{'stepIndex':1,'outputId':'rendered','selector':'all'}]
    feedback=boundary.qualified_field_feedback(value,{'E1':'owned'})
    assert any(i['code']=='timeline.input.group_leak' for i in feedback['issues'])
