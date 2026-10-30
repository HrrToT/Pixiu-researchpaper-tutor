from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_evaluation_groups as grouped
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import descriptor_for,options_for_record
from test_deep_research_workflow_evaluation_groups import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair,response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def test_missing_control_measurement_gets_one_revision_then_full_assembly_and_resume():
    good=wire_value();bad=deepcopy(good);bad['steps'][2]['group']='1'
    r,original,invoke,run=setup_repair([response(bad),response(good),*map(response,explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=21,workflowInitializationOutputContractVersion=1)
    saved=run();repair=saved['metadataRepair']
    assert saved['status']=='ready' and repair['value']==grouped.decode(good)
    assert saved['units']['metadata']['response']==response(bad)
    data=input_value(repair['request']['prompt'])
    assert data['invalidMetadata']==bad
    assert data['authoritativeInput']==json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert any(i['code']=='evaluation.coverage' and i['missingGroups']==['0'] for i in data['fieldFeedback']['issues'])
    assert repair['request']['extra']['response_format']==grouped.descriptor()
    assert run()==saved and invoke.call_count==5 and not saved['scientificApproval']


def test_unchanged_missing_control_result_is_rejected_without_extra_attempt():
    bad=wire_value();bad['steps'][2]['group']='1'
    r,_,invoke,run=setup_repair([response(bad),response(bad)])
    r['workflowMetadataRepairContractVersion']=21
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2
    assert r['state']['executionWorkflowBlueprint']['metadataRepair']['errors']==['unit.json']


def test_shared_evaluation_uses_original_assembly_and_binding():
    from test_deep_research_workflow5_contract import claims
    from services.deep_research.execution_workflow_blueprint import errors,bind
    value=wire_value();step=value['steps'][2]
    step.update(kind='evaluate_shared',groups=['0','1'],sharing='shared');step.pop('group')
    r,_,invoke,run=setup_repair([response(value),*map(response,explicit_initializers())])
    r['workflowMetadataRepairContractVersion']=21
    saved=run()
    assert saved['status']=='ready' and errors(saved['value'],{'E1':'owned'},version=7)==[]
    rows=claims();rows[-1].pop('executionSpec')
    result,binding=bind({'claims':rows},saved)
    assert any(p['kind']=='evaluate' and p['sharing']=='shared' for p in result['claims'][-1]['executionSpec']['phases'])
    assert not binding['scientificApproval'] and run()==saved and invoke.call_count==4


def test_native_role_limits_and_legacy_descriptor_remain_unchanged():
    r,_,_,_=setup_repair([]);r['workflowMetadataRepairContractVersion']=20
    old=descriptor_for(r,'plan_workflow_meta')
    r['workflowMetadataRepairContractVersion']=21
    for node in ('plan_workflow_meta','repair_workflow_meta'):
        options=options_for_record(r,node,{'temperature':0.0})
        assert options['response_format']==grouped.descriptor()
        assert options['max_tokens']==3072 and options['reasoning_effort']=='none'
    r['workflowMetadataRepairContractVersion']=20
    assert descriptor_for(r,'plan_workflow_meta')==old
