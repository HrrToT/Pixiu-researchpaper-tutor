from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_metadata_result_refs as refs
from services.deep_research import workflow_metadata_first_use as old
from services.deep_research.workflow_units import META, unit_errors
from services.deep_research.contracts import DeepResearchError
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def authored():
    value = wire_value()
    for step in value['steps']:
        for read in step['reads']:
            if 'stepIndex' not in read: continue
            stage = read.pop('outputStage')
            if stage == 'record': read['savedOutputId'] = read.pop('outputId')
    return value


def test_direct_refs_preserve_all_explicit_choices_and_canonical_wiring():
    value = authored(); before = deepcopy(value)
    assert refs.decode(value) == old.decode(wire_value()) and value == before
    assert unit_errors(refs.decode(value), {'E1':'owned'}, node=META, version=7, metadata_rows=True) == []
    schema = refs.descriptor()['schema']; Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize('saved,stage', [(False,'measurement'), (True,'record')])
def test_same_named_observation_and_saved_outputs_have_explicit_distinct_choices(saved,stage):
    field = 'savedOutputId' if saved else 'outputId'
    value = {'steps':[
        {'kind':'observe','outputs':['same'],'recording':{'outputs':['same']},'reads':[]},
        {'kind':'setup','reads':[{'stepIndex':0,field:'same','selector':'chosen exact slice'}]}]}
    before = deepcopy(value); result, issues = refs.expanded(value)
    assert not issues and value == before
    assert result['steps'][1]['reads'][0] == {
        'stepIndex':0,'outputStage':stage,'outputId':'same','selector':'chosen exact slice'}


def test_saved_choice_is_accepted_by_the_complete_native_format():
    from test_deep_research_workflow_metadata_bounded_schema import fixtures
    value = fixtures()[3]
    for step in value['steps']:
        for read in step['reads']:
            if 'stepIndex' in read:
                stage = read.pop('outputStage')
                if stage == 'record': read['savedOutputId'] = read.pop('outputId')
    producer_index, producer = next((i,s) for i,s in enumerate(value['steps']) if s['kind']=='observe')
    template = authored()['steps'][4]
    template.update(group=producer['group'], scope=producer['scope'], outputs=['saved_copy'], reads=[{
        'stepIndex':producer_index,'savedOutputId':producer['recording']['outputs'][0],'selector':'all'}])
    value['steps'].append(template)
    assert Draft202012Validator(refs.descriptor()['schema']).is_valid(value)
    assert refs.expanded(value)[1] == []
    assert 'Never author outputStage' in refs.POLICY and 'outputStage=operation' not in refs.POLICY


def test_saved_reference_cannot_switch_to_a_primitive_or_guess_a_different_output():
    value = authored(); value['steps'][2]['reads'] = [{'stepIndex':0,'savedOutputId':'selected','selector':'all'}]
    assert refs.expanded(value)[1][0]['code'] == 'result_ref.saved_source'
    with pytest.raises(ValueError): refs.decode(value)
    value['steps'][2]['reads'] = [{'stepIndex':0,'outputId':'missing','selector':'all'}]
    issue = refs.expanded(value)[1][0]
    assert issue['code'] == 'result_ref.output' and issue['actual'] == 'missing'
    assert issue['declaredOutputs'] == value['steps'][0]['outputs']


@pytest.mark.parametrize('recording', [None, [], True, 'broken'])
def test_malformed_recording_is_rejected_without_an_attribute_exception(recording):
    value = {'steps':[
        {'kind':'observe','outputs':['m'],'recording':recording,'reads':[]},
        {'kind':'record','reads':[{'stepIndex':0,'savedOutputId':'m','selector':'all'}]}]}
    assert refs.expanded(value)[1][0]['code'] == 'result_ref.output'
    with pytest.raises(ValueError): refs.decode(value)


@pytest.mark.parametrize('index', [True,-1,999,'0'])
def test_invalid_producer_index_is_never_coerced(index):
    value = authored(); value['steps'][2]['reads'] = [{'stepIndex':index,'outputId':'selected','selector':'all'}]
    assert refs.expanded(value)[1][0]['code'] == 'result_ref.index'
    with pytest.raises(ValueError): refs.decode(value)


def test_previous_stage_field_is_rejected_in_new_wire_and_old_decoder_is_unchanged():
    value = authored(); value['steps'][2]['reads'] = [{
        'stepIndex':0,'outputStage':'operation','outputId':'selected','selector':'all'}]
    assert refs.expanded(value)[1][0]['code'] == 'result_ref.fields'
    assert not Draft202012Validator(refs.descriptor()['schema']).is_valid(value)
    with pytest.raises(ValueError): refs.decode(value)
    assert old.decode(wire_value())


def test_exact_producer_and_groups_still_apply_and_feedback_shows_authored_fields():
    value = authored(); read = {'stepIndex':1,'outputId':'rendered','selector':'all'}
    value['steps'][2]['reads'] = [read]
    errors = unit_errors(refs.decode(value), {'E1':'owned'}, node=META, version=7, metadata_rows=True)
    assert 'timeline.input.group_leak' in errors
    issue = next(i for i in refs.field_feedback(value,{'E1':'owned'})['issues'] if i['code']=='timeline.input.group_leak')
    assert issue['actual'] == read and 'outputStage' not in issue['actual']
    value['steps'][2]['reads'] = [{'stepIndex':3,'outputId':'metrics','selector':'all'}]
    assert 'timeline.input.future_output' in unit_errors(refs.decode(value),{'E1':'owned'},node=META,version=7,metadata_rows=True)


def test_one_revision_full_assembly_resume_and_original_preservation():
    good = authored(); bad = deepcopy(good)
    bad['steps'][2]['reads'] = [{'stepIndex':0,'outputId':'missing','selector':'all'}]
    r, _, invoke, run = setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=27,workflowInitializationOutputContractVersion=1)
    saved = run(); fix = saved['metadataRepair']
    assert saved['status'] == fix['status'] == 'ready' and fix['version'] == 27
    assert saved['units']['metadata']['response'] == response(bad)
    assert input_value(fix['request']['prompt'])['invalidMetadata'] == bad
    assert run() == saved and invoke.call_count == 5


def test_invalid_ref_is_not_fixed_automatically_or_retried():
    bad = authored(); bad['steps'][2]['reads'] = [{'stepIndex':0,'outputId':'missing','selector':'all'}]
    r, _, invoke, run = setup_repair([response(bad),response(bad)])
    r.update(workflowMetadataRepairContractVersion=27,workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError): run()
    assert invoke.call_count == 2
