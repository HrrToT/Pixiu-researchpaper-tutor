from copy import deepcopy
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.workflow_metadata_objects import encode,decode,descriptor,field_feedback,NAME
from services.deep_research.workflow_metadata_repair import load_wire
from services.deep_research.workflow_units import META,unit_errors,descriptor as unit_descriptor
from test_deep_research_workflow_lifecycle_units import fixtures
from test_deep_research_workflow_metadata_repair import setup_repair,response,invalid_metadata


def test_output_is_exact_canonical_metadata_and_reuses_complete_named_schema():
    meta=fixtures()[1];before=deepcopy(meta)
    assert encode(meta)==decode(meta)==before
    schema=descriptor();expected=unit_descriptor(META,7);expected['name']=NAME
    assert schema==expected
    assert set(schema['schema']['properties'])==set(meta)
    assert schema['schema']['$defs']['lifecycle']['properties']['createAfter']['type']=='array'
    assert not field_feedback(meta,{'E1':'owned'})['issues']
    assert meta==before


@pytest.mark.parametrize('change',['old_rows','missing','extra','component_fields','phase_fields','nonfinite'])
def test_unknown_or_incomplete_outer_objects_are_never_translated_or_filled(change):
    meta=fixtures()[1]
    if change=='old_rows':
        from services.deep_research.workflow_metadata_rows import encode as rows
        meta=rows(meta)
    elif change=='missing':del meta['phases']
    elif change=='extra':meta['unexpected']='must not disappear'
    elif change=='component_fields':meta['components'][0]['unexpected']='retain'
    elif change=='phase_fields':del meta['phases'][0]['updates']
    else:meta['unresolved']=[float('nan')]
    with pytest.raises(ValueError):decode(meta)


def test_bad_lifecycle_scalar_is_retained_and_explained_at_named_field():
    meta=invalid_metadata();before=deepcopy(meta)
    assert decode(meta)==before
    assert 'timeline.component.lifecycle' in unit_errors(meta,{'E1':'owned'},node=META,version=7,metadata_rows=True)
    feedback=field_feedback(meta,{'E1':'owned'})
    issue=next(x for x in feedback['issues'] if x['path']=='/components/0/lifecycle/createAfter')
    assert issue['actual']=='not_an_array' and issue['actualPresent']
    assert meta==before and not feedback['scientificApproval']


@pytest.mark.parametrize('revision_version', [8, 9])
def test_new_generation_and_revision_prompts_have_only_named_output_instructions_and_resume(revision_version):
    _,meta,inits=fixtures();bad=invalid_metadata()
    r,_,invoke,run=setup_repair([response(bad),response(meta),*map(response,inits)])
    r['workflowMetadataRepairContractVersion']=revision_version
    result=run();request=result['units']['metadata']['request']
    prefix=request['prompt'].split('Exact authoritative input and unit context',1)[0]
    assert NAME in prefix and 'phaseRows columns:' not in prefix
    assert 'Each read is [state,selector]' not in prefix and 'workflow_metadata_rows_v1' not in prefix
    assert request['extra']['response_format']['name']==NAME
    assert result['units']['metadata']['value']==bad
    assert result['metadataRepair']['status']=='ready' and result['metadataRepair']['version']==revision_version
    calls=invoke.call_count
    assert run()==result and invoke.call_count==calls and not result['scientificApproval']


@pytest.mark.parametrize('kind',['content','raw','truncated','duplicate'])
def test_content_storage_truncation_and_duplicate_key_limits_still_block_revision(kind):
    meta=invalid_metadata();bad=response(meta)
    if kind=='content':meta['unresolved']=['x'*9000];bad=response(meta)
    elif kind=='raw':bad['rawContent']=bad['content']+' '*17000
    elif kind=='truncated':bad['finishReason']='length'
    else:bad['rawContent']='{"sourceRefs":[],"sourceRefs":[]}'
    r,_,invoke,run=setup_repair([bad]);r['workflowMetadataRepairContractVersion']=8
    for _ in range(2):
        with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==1 and 'metadataRepair' not in r['state']['executionWorkflowBlueprint']


def test_duplicate_keys_are_not_lost_in_named_canonical_object_parsing():
    with pytest.raises(ValueError):load_wire('{"phases":[],"phases":[]}',8)


def test_bad_fit_budget_and_same_phase_creation_use_are_explained_without_decisions():
    meta=fixtures()[1];meta['phases'][0]['budget']=None
    meta['components'][0]['lifecycle']['createAfter']=['stage1'];before=deepcopy(meta)
    result=field_feedback(meta,{'E1':'owned'})
    budget=next(x for x in result['issues'] if x['code']=='timeline.phase.budget')
    assert budget['path']=='/phases/0/budget' and budget['actual'] is None
    uses=[x for x in result['issues'] if x['code']=='metadata.lifecycle.before_creation']
    assert {x['path'] for x in uses}=={'/phases/0/reads/1','/phases/0/updates/0'}
    assert meta==before
