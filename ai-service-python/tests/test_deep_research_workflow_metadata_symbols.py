from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_metadata_symbols as symbols
from services.deep_research import workflow_metadata_result_refs as old
from services.deep_research.workflow_units import META, unit_errors
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import descriptor_for
from test_deep_research_workflow_metadata_result_refs import authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def pair(source=None):
    explicit = deepcopy(source) if source is not None else authored()
    for step in explicit['steps']:
        for read in step['reads']:
            stage=read.pop('outputStage',None)
            if stage=='record':read['savedOutputId']=read.pop('outputId')
    from collections import Counter
    counts = Counter(name for step in explicit['steps']
        for block in (step, step.get('recording', {})) for name in block.get('outputs', []))
    names = {}
    for i, step in enumerate(explicit['steps']):
        for field, block in [('outputId', step), ('savedOutputId', step.get('recording', {}))]:
            outputs = block.get('outputs', [])
            for j, name in enumerate(outputs):
                names[(i, field, name)] = name if counts[name] == 1 else f'result_{i}_{field}_{j}'
            block['outputs'] = [names[(i, field, name)] for name in outputs]
        recording = step.get('recording')
        if recording:
            for read in recording['inputs']:
                read['outputId'] = names[(i, 'outputId', read['outputId'])]
    for step in explicit['steps']:
        for read in step['reads']:
            if 'stepIndex' in read:
                field = 'savedOutputId' if 'savedOutputId' in read else 'outputId'
                read[field] = names[(read['stepIndex'], field, read[field])]
    symbolic = deepcopy(explicit)
    for step in symbolic['steps']:
        for i, read in enumerate(step['reads']):
            if 'stepIndex' in read:
                field = 'savedOutputId' if 'savedOutputId' in read else 'outputId'
                step['reads'][i] = {'result': read[field], 'selector': read['selector']}
    return explicit, symbolic


def test_symbolic_compiler_preserves_canonical_plan_and_never_mutates_input():
    explicit, value = pair(); before = deepcopy(value)
    assert symbols.decode(value) == old.decode(explicit)
    assert value == before
    schema = symbols.descriptor()['schema']; Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(value)
    assert 'stepIndex' not in symbols.POLICY.split('never supply stepIndex')[0]
    assert unit_errors(symbols.decode(value), {'E1':'owned'}, node=META, version=7, metadata_rows=True) == []


@pytest.mark.parametrize('outputs', [[], ['x','x'], [True], 'x'])
def test_save_all_requires_valid_authored_measurement_outputs(outputs):
    value = {'steps':[{'kind':'observe','outputs':outputs,'reads':[],
                      'recording':{'inputs':'all_measurements','outputs':['saved']}}]}
    assert symbols.expanded(value)[1][0]['code'] == 'symbol.measurements'


def test_save_all_expands_every_output_and_preserves_authored_instruction():
    value = {'steps':[{'kind':'observe','outputs':['images','psnr'],'reads':[],
                      'recording':{'inputs':'all_measurements','outputs':['saved']}}]}
    before = deepcopy(value); lowered, issues = symbols.expanded(value)
    assert issues == [] and value == before
    assert lowered['steps'][0]['recording']['inputs'] == [
        {'outputId':'images','selector':'all'}, {'outputId':'psnr','selector':'all'}]
    assert lowered['steps'][0]['recording']['outputs'] == ['saved']


def test_full_observation_schema_and_canonical_checks_accept_save_all_directive():
    from test_deep_research_workflow_metadata_bounded_schema import fixtures
    _, value=pair(fixtures()[3]); before=deepcopy(value)
    observations=[s for s in value['steps'] if s['kind']=='observe']
    assert observations
    for step in observations:step['recording']['inputs']='all_measurements'
    frozen=deepcopy(value)
    assert Draft202012Validator(symbols.descriptor()['schema']).is_valid(value)
    lowered,issues=symbols.expanded(value)
    assert not issues and symbols.decode(value)==old.decode(lowered) and value==frozen
    assert unit_errors(symbols.decode(value),{'E1':'owned'},node=META,version=7,metadata_rows=True)==[]
    assert any(s.get('recording',{}).get('inputs')!='all_measurements' for s in before['steps'])


@pytest.mark.parametrize('name', ['absent', None, True, []])
def test_unknown_symbols_are_not_coerced_or_selected(name):
    _, value = pair(); value['steps'][2]['reads'] = [{'result':name,'selector':'all'}]
    assert symbols.expanded(value)[1][0]['code'] == 'symbol.missing'
    with pytest.raises(ValueError): symbols.decode(value)


def test_same_named_measurement_and_saved_result_is_ambiguous_not_guessed():
    value = {'steps':[{'kind':'observe','outputs':['x'],'reads':[],
        'recording':{'outputs':['x']}}, {'kind':'record','reads':[{'result':'x','selector':'all'}]}]}
    issue = symbols.expanded(value)[1][0]
    assert issue['code'] == 'symbol.ambiguous' and len(issue['producers']) == 2


def test_group_and_future_checks_survive_compilation_with_authored_feedback():
    _, value = pair(); name=value['steps'][1]['outputs'][0]
    value['steps'][2]['reads'] = [{'result':name,'selector':'all'}]
    assert 'timeline.input.group_leak' in unit_errors(symbols.decode(value), {'E1':'owned'}, node=META,version=7,metadata_rows=True)
    issue=next(i for i in symbols.field_feedback(value,{'E1':'owned'})['issues'] if i['code']=='timeline.input.group_leak')
    assert issue['actual']==value['steps'][2]['reads'][0] and issue['path']=='/steps/2/reads/0'
    value['steps'][2]['reads'] = [{'result':value['steps'][3]['outputs'][0],'selector':'all'}]
    assert 'timeline.input.future_output' in unit_errors(symbols.decode(value), {'E1':'owned'},node=META,version=7,metadata_rows=True)


def test_explicit_producer_indices_are_rejected_only_in_new_compiler():
    explicit, _ = pair()
    assert symbols.expanded(explicit)[1][0]['code']=='symbol.fields'
    with pytest.raises(ValueError): symbols.decode(explicit)
    assert old.decode(explicit)


def test_integration_one_repair_preserves_original_wire_and_resumes_without_calls():
    _, good = pair(); bad=deepcopy(good);bad['steps'][2]['reads']=[{'result':'missing','selector':'all'}]
    r, _, invoke, run=setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=34,workflowInitializationOutputContractVersion=1)
    assert descriptor_for(r,META)['name']=='metadata_symbolic_results_v1'
    saved=run();fix=saved['metadataRepair']
    assert saved['status']==fix['status']=='ready' and fix['version']==34
    assert saved['units']['metadata']['response']==response(bad)
    assert input_value(fix['request']['prompt'])['invalidMetadata']==bad
    assert run()==saved and invoke.call_count==5 and not saved['scientificApproval']


def test_failed_unique_repair_does_not_resend_on_resume():
    _, bad=pair();bad['steps'][2]['reads']=[{'result':'missing','selector':'all'}]
    r, _, invoke, run=setup_repair([response(bad),response(bad)])
    r.update(workflowMetadataRepairContractVersion=34,workflowInitializationOutputContractVersion=1)
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2


def test_no_repair_path_uses_symbolic_schema_and_durable_canonical_value():
    explicit, good=pair()
    r, _, invoke, run=setup_repair([response(good),*map(response,explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=34,workflowInitializationOutputContractVersion=1)
    saved=run()
    assert saved['status']=='ready' and 'metadataRepair' not in saved
    assert saved['units']['metadata']['value']==old.decode(explicit)
    assert run()==saved and invoke.call_count==4


def test_new_mode_does_not_inherit_reasoning_experiment():
    from services.deep_research.workflow_transport import reasoning_options
    from services.deep_research.workflow_metadata_repair import prompt_for
    record={'workflowMetadataRowsContractVersion':2,'workflowMetadataRepairContractVersion':34,
        'executionWorkflowContractVersion':7,'workflowContractVersion':5,
        'experimentPlanEncodingContractVersion':7}
    # Output limits remain governed by the existing transport. Version 33's
    # isolated provider reasoning experiment must not leak into this path.
    options=reasoning_options(record, 'repair_workflow_meta', {'max_tokens':6144})
    assert options.get('reasoning_effort') != 'low'
    assert 'all_measurements' in prompt_for('{}',{}, {},version=34)
