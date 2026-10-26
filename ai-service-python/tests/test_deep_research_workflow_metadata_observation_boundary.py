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


@pytest.mark.parametrize('version', [28, 29, 30, 31])
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


@pytest.mark.parametrize('version', [28, 29, 30, 31])
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


@pytest.mark.parametrize('version', [28, 29, 30, 31])
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


@pytest.mark.parametrize('refs', [['P1'],['E1','E1'],[['E1']], 'E1', ['E1']*21])
def test_source_reference_feedback_preserves_bad_value_and_does_not_choose_evidence(refs):
    value=authored();value['sourceRefs']=refs;before=deepcopy(value)
    old=boundary.qualified_field_feedback(value, {'E1':'owned','E2':'other'})
    result=boundary.complete_field_feedback(value, {'E1':'owned','E2':'other'})
    assert not any(i['code']=='unit.sourceRefs' for i in old['issues'])
    assert any(i['code']=='unit.sourceRefs' and i['path'].startswith('/sourceRefs') for i in result['issues'])
    assert result['allowedSourceRefs']==['E1','E2']
    assert value==before and not result['scientificApproval']


@pytest.mark.parametrize('gaps', [None,[''],['unresolved']*9])
def test_gap_envelope_error_has_its_own_path_without_fabricated_resolution(gaps):
    value=authored();value['unresolved']=gaps;before=deepcopy(value)
    result=boundary.complete_field_feedback(value, {'E1':'owned'})
    assert any(i['code']=='unit.unresolved' and i['path'].startswith('/unresolved') for i in result['issues'])
    assert value==before


@pytest.mark.parametrize('field', ['baselineMode','replicationMode'])
def test_invalid_mode_has_exact_path_and_choices_but_no_automatic_replacement(field):
    value=authored();value[field]='unknown_mode';before=deepcopy(value)
    result=boundary.complete_field_feedback(value, {'E1':'owned'})
    issue=next(i for i in result['issues'] if i['path']=='/'+field)
    assert issue['actual']=='unknown_mode' and isinstance(issue['expected'],list)
    assert value==before


def test_evidence_alias_context_and_multiple_errors_are_in_one_durable_revision():
    good=authored();bad=deepcopy(good);bad['sourceRefs']=['P1']
    bad['steps'][0]['updates']=['not_a_declared_state']
    record, _, invoke, run=setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    record.update(workflowMetadataRepairContractVersion=31,workflowInitializationOutputContractVersion=1)
    saved=run();fix=saved['metadataRepair'];data=input_value(fix['request']['prompt'])
    generation=input_value(saved['units']['metadata']['request']['prompt'])
    assert generation['unitContext']['allowedSourceRefs']==['E1']
    assert data['invalidMetadata']==bad
    assert data['fieldFeedback']['allowedSourceRefs']==['E1']
    assert any(i['path']=='/sourceRefs/0' and i['actual']=='P1' for i in data['fieldFeedback']['issues'])
    assert any(i['code']=='metadata.update.unknown' for i in data['fieldFeedback']['issues'])
    assert saved['status']==fix['status']=='ready'
    assert run()==saved and invoke.call_count==5


def test_valid_source_alias_is_not_a_support_or_scientific_approval():
    value=authored();result=boundary.complete_field_feedback(value, {'E1':'owned'})
    assert 'allowedSourceRefs' not in result and not result['scientificApproval']
    data=json.dumps({'sources':'unaltered'})
    prompt=prompt_for(data,value,result,version=31)
    assert 'syntax permission, not evidence of support' in prompt
    assert input_value(prompt)==input_value(prompt_for(data,value,result,version=30))
