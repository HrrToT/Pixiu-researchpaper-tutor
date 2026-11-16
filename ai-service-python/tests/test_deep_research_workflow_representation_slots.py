"""Fixed target/source identities, reversible wire, unchanged content guards."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from services.deep_research import workflow_representation_slots as slots
from services.deep_research import workflow_representation as types
from services.deep_research import workflow_representation_stage as stage
from services.deep_research import workflow_representation_input_first as indexed
from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.workflow_units import INIT
from services.deep_research.planning_transport import descriptor_for
import test_deep_research_workflow_representation_input_first as previous
import test_deep_research_workflow_representation_stage as stage_tests

original_setup=previous.setup


def fixture():
    record,native,canonical,metadata,calls=previous.fixture()
    for target in canonical['targets']:
        for variable in target['states']:
            variable['encoding']=slots._encoding(['explicit fixture domain','identity','identity','fixture units/channels'])
    return record,slots.encode(canonical,metadata),canonical,metadata,calls


def setup():
    record,invoke,run=original_setup();record[stage.MARKER]=4
    calls=list(invoke.side_effect);metadata=json.loads(calls[0]['content'])
    canonical=indexed.decode(json.loads(calls[1]['content']))
    for target,call in zip(canonical['targets'],calls[2:]):
        wire=json.loads(call['content'])
        for variable,row in zip(target['states'],wire['stateSemantics']):
            variable['encoding']=slots._encoding(['explicit fixture domain','identity','identity','fixture units/channels'])
            row[2]=variable['encoding']
        call['content']=json.dumps(wire)
    calls[1]['content']=json.dumps(slots.encode(canonical,metadata));invoke.side_effect=calls
    return record,invoke,run


def test_exact_slot_counts_source_choices_and_reversible_model_values():
    record,native,canonical,metadata,calls=fixture();schema=types.descriptor(4,metadata=metadata)['schema']
    Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(native)
    before=deepcopy((native,metadata))
    assert slots.decode(native,metadata)==canonical and slots.encode(canonical,metadata)==native
    assert (native,metadata)==before
    assert types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=4)==[]
    assert native['metadataDigest']==digest(metadata)
    assert len(native['inputRows'])==len(native['variableGroups'])==len(metadata['components'])+1
    assert slots.catalogues(metadata)[0]=={'target':'baseline','sources':[{'state':'training_data'}]}
    assert 'target' not in native and all('target' not in v for group in native['variableGroups'] for v in group)


@pytest.mark.parametrize('change',['missing_input_slot','missing_variable_slot','extra_input_slot','extra_variable_slot',
    'future_source','negative_source','bool_source','float_source','wrong_digest','unknown_key','bad_row_width',
    'bad_encoding_width','dtype_encoding_only','old_wire'])
def test_omissions_invented_sources_and_wrong_metadata_cannot_compile(change):
    _,native,_,metadata,_=fixture()
    if change=='missing_input_slot':native['inputRows'].pop()
    elif change=='missing_variable_slot':native['variableGroups'].pop()
    elif change=='extra_input_slot':native['inputRows'].append([])
    elif change=='extra_variable_slot':native['variableGroups'].append([])
    elif change in ('future_source','negative_source','bool_source','float_source'):
        native['inputRows'][0]=[[{'future_source':1,'negative_source':-1,'bool_source':False,'float_source':0.0}[change],
            {'entity':'model','fields':['values'],'axes':['rows']},'proposal',[]]]
    elif change=='wrong_digest':native['metadataDigest']='different'
    elif change=='unknown_key':native['filledTarget']='invented'
    elif change=='bad_row_width':native['inputRows'][-1][0].append('not ignored')
    elif change=='bad_encoding_width':native['variableGroups'][0][0]['encoding']=['domain']
    elif change=='dtype_encoding_only':native['variableGroups'][0][0]['encoding']='float32'
    else:native=indexed.encode(slots.decode(native,metadata))
    with pytest.raises(ValueError):slots.decode(native,metadata)
    # JSON Schema considers 0.0 an integer; the compiler deliberately requires
    # an actual integer index, just like the existing canonical state contract.
    if change!='float_source':
        assert list(Draft202012Validator(slots.descriptor(metadata)['schema']).iter_errors(native))


def test_same_wire_cannot_be_rebound_to_changed_group_or_lifecycle_context():
    _,native,_,metadata,_=fixture();changed=deepcopy(metadata)
    changed['components'][0]['appliesTo']=list(reversed(changed['components'][0]['appliesTo']))+['other']
    with pytest.raises(ValueError):slots.decode(native,changed)
    assert slots.descriptor(changed)!=slots.descriptor(metadata)


def test_encoding_and_numeric_fields_are_not_filled_or_approved():
    _,native,_,metadata,_=fixture();native['variableGroups'][0][0].pop('dtype')
    canonical=slots.decode(native,metadata)
    assert 'representation.schema' in {e['code'] for e in types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=4)}
    with pytest.raises(ValueError):types.freeze(canonical,metadata,{'E1':'a','E2':'b'},version=4)
    _,_,canonical,metadata,_=fixture();canonical['targets'][0]['states'][0]['encoding']='float32'
    assert 'representation.encoding' in {e['code'] for e in types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=4)}


def test_complete_flow_uses_frozen_metadata_and_preserves_raw_rows_and_encoding():
    record,invoke,run=setup();saved=run()
    assert saved['status']=='ready' and invoke.call_count==5
    shared=saved['representation'];raw=json.loads(shared['response']['content'])
    assert slots.decode(raw,shared['metadata'])==shared['value']
    assert shared['frozen']['version']==4 and shared['scientificApproval'] is False
    assert slots.metadata_for_record(record)==shared['metadata']
    assert shared['request']['extra']['response_format']==slots.descriptor(shared['metadata'])
    assert run()==saved and invoke.call_count==5


@pytest.mark.parametrize('change',['missing','pending','raw','value','alias','wrong_repair'])
def test_request_schema_cannot_bind_missing_unready_or_tampered_metadata(change):
    record,invoke,run=setup();run();metadata=record['state']['executionWorkflowBlueprint']['units']['metadata']
    if change=='missing':record['state']['executionWorkflowBlueprint']['units'].pop('metadata')
    elif change=='pending':metadata['status']='pending'
    elif change=='raw':metadata['response']['content']='{}'
    elif change=='value':metadata['value']['baselineMode']='existing'
    elif change=='alias':record['state']['executionWorkflowBlueprint']['aliases']={}
    else:metadata['status']='invalid_response'
    with pytest.raises(ValueError):descriptor_for(record,stage.NODE)


def test_effective_metadata_repair_is_verified_against_its_original_parent():
    record,invoke,run=setup();run();bp=record['state']['executionWorkflowBlueprint'];unit=bp['units']['metadata']
    good=deepcopy(unit);unit.update(status='invalid_response',errors=['fixture.original_error'])
    good['parent']={'requestDigest':digest(unit['request']),'responseDigest':unit['responseDigest'],
                    'valueDigest':unit['valueDigest'],'errors':unit['errors']}
    bp['metadataRepair']=good
    assert slots.metadata_for_record(record)==good['value']
    good['parent']['responseDigest']='other'
    with pytest.raises(ValueError):slots.metadata_for_record(record)


@pytest.mark.parametrize('rows',[True,False])
def test_metadata_keeps_its_existing_profile_specific_expansion_limit(rows):
    record,invoke,run=setup();run();unit=record['state']['executionWorkflowBlueprint']['units']['metadata']
    unit['value']['phases'][0]['action']['action']='long unverified action '+('x'*9000)
    unit['valueDigest']=digest(unit['value'])
    unit['response']['content']=json.dumps(unit['value']);unit['responseDigest']=digest(unit['response'])
    record['workflowMetadataRowsContractVersion']=1 if rows else 0
    size=len(json.dumps(unit['value'],separators=(',',':')).encode())
    assert 8192<size<32000
    if rows:assert slots.metadata_for_record(record)==unit['value']
    else:
        with pytest.raises(ValueError):slots.metadata_for_record(record)


@pytest.mark.parametrize('version,accepted',[(3,False),(4,True)])
def test_format_whitespace_does_not_expand_canonical_content_or_change_old_raw_guard(version,accepted):
    record,invoke,run=setup() if version==4 else previous.setup()
    calls=list(invoke.side_effect);calls[1]['content']=' '*17000+calls[1]['content'];invoke.side_effect=calls
    if accepted:assert run()['status']=='ready'
    else:
        with pytest.raises(DeepResearchError):run()
        assert record['state']['executionWorkflowBlueprint']['representation']['status']=='invalid_response'


def test_new_raw_guard_and_unchanged_semantic_cap_both_remain_enforced():
    record,invoke,run=setup();calls=list(invoke.side_effect)
    calls[1]['content']=' '*slots.RAW_BYTES+calls[1]['content'];invoke.side_effect=calls
    with pytest.raises(DeepResearchError):run()
    assert {'code':'representation.capacity','path':''} in record['state']['executionWorkflowBlueprint']['representation']['errors']
    _,_,canonical,metadata,_=fixture()
    canonical['targets'][0]['states'][0]['encoding']=slots._encoding(['domain','x'*16384,'inverse','units'])
    assert types.issues(canonical,metadata,{'E1':'a','E2':'b'},version=4)==[{'code':'representation.capacity','path':''}]


def test_v3_cached_workflow_does_not_upgrade_or_resend():
    record,invoke,run=previous.setup();run();count=invoke.call_count;record[stage.MARKER]=4
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


def test_one_initializer_repair_keeps_structured_encoding_types_and_source_permissions():
    record,invoke,run=setup();calls=list(invoke.side_effect);good=deepcopy(calls[-1]);bad=deepcopy(good)
    value=json.loads(bad['content']);value['initialization']['stateDefinitions'][0]['dtype']='wrong'
    bad['content']=json.dumps(value);invoke.side_effect=[*calls[:-1],bad,good]
    saved=run();assert saved['initializationRepair']['status']=='ready' and invoke.call_count==6
    assert saved['initializationRepair']['request']['extra']['response_format']['name'].startswith('workflow_init_representation_v4_')
    assert run()==saved and invoke.call_count==6


def test_encoding_is_readable_and_escaped_by_existing_report_boundary():
    from services.deep_research.workflow_initialization_semantics import decode
    from services.deep_research.workflow_lifecycle_text import _initialization
    _,native,_,metadata,calls=fixture();native['variableGroups'][0][0]['encoding'][1]='<script> source text'
    value=slots.decode(native,metadata);encoding=value['targets'][0]['states'][0]['encoding']
    assert '物理域' in slots.encoding_text(encoding) and slots.encoding_rows(encoding)[1]=='<script> source text'
    wire=json.loads(calls[2]['content']);wire['stateSemantics'][0][2]=encoding
    text='\n'.join(_initialization(decode(wire)['initialization'],'fixture'))
    assert '<script>' not in text and '&lt;script&gt;' in text and '@representation-encoding' not in text


@pytest.mark.parametrize('node',[stage.NODE,INIT])
@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_actual_v4_http_binding_budget_unknown_no_resend(tmp_path,monkeypatch,node,scenario):
    monkeypatch.setattr(stage_tests,'setup',setup)
    stage_tests.test_actual_provider_payload_ledger_identity_capacity_and_unknown_no_resend(tmp_path,monkeypatch,node,scenario)
