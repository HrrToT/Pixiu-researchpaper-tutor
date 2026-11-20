from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_fit_budget as typed
from services.deep_research.contracts import DeepResearchError
from services.deep_research.planning_transport import options_for_record, descriptor_for
from test_deep_research_workflow_scope_position import wire_value
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


def test_missing_budget_original_survives_one_revision_and_full_assembly_resume():
    good=wire_value();bad=deepcopy(good);bad['steps'][0]['budget']=None
    r,original,invoke,run=setup_repair([
        response(bad),response(good),*map(response,explicit_initializers())])
    r.update(workflowMetadataRepairContractVersion=20,workflowInitializationOutputContractVersion=1)
    saved=run();repair=saved['metadataRepair']
    assert saved['status']=='ready' and repair['value']==typed.decode(good)
    assert saved['units']['metadata']['response']==response(bad)
    assert saved['units']['metadata']['errors']==['timeline.phase.budget']
    data=input_value(repair['request']['prompt'])
    assert data['invalidMetadata']==bad
    assert data['authoritativeInput']==json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    assert any(i['path']=='/steps/0/budget' and i['actual'] is None for i in data['fieldFeedback']['issues'])
    assert repair['request']['extra']['response_format']==typed.descriptor()
    assert run()==saved and invoke.call_count==5 and not saved['scientificApproval']


def test_provider_returning_null_again_is_rejected_without_filling_or_resending():
    bad=wire_value();bad['steps'][0]['budget']=None
    r,_,invoke,run=setup_repair([response(bad),response(bad)])
    r['workflowMetadataRepairContractVersion']=20
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==2
    repair=r['state']['executionWorkflowBlueprint']['metadataRepair']
    assert repair['response']==response(bad) and repair['errors']==['timeline.phase.budget']


def test_new_native_schema_keeps_role_budget_and_legacy_descriptor():
    r,_,_,_=setup_repair([]);r['workflowMetadataRepairContractVersion']=19
    old=descriptor_for(r,'plan_workflow_meta')
    r['workflowMetadataRepairContractVersion']=20
    for node in ('plan_workflow_meta','repair_workflow_meta'):
        options=options_for_record(r,node,{'temperature':0.0})
        assert options['response_format']==typed.descriptor()
        assert options['max_tokens']==3072 and options['reasoning_effort']=='none'
    r['workflowMetadataRepairContractVersion']=19
    assert descriptor_for(r,'plan_workflow_meta')==old
