from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_scope_end as scoped
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_metadata_scope_end_integration import scope_authored
from test_deep_research_workflow_metadata_steps_integration import explicit_initializers
from test_deep_research_workflow_metadata_repair import setup_repair, response
from test_deep_research_workflow_metadata_ordered_integration import input_value


@pytest.mark.parametrize('count', [0, -1, True, 1.5, '3'])
def test_invalid_frame_count_is_retained_with_exact_relation_and_no_suggested_value(count):
    wire = scope_authored(); wire['frameIterations'] = count; before = deepcopy(wire)
    assert 'timeline.frameIterations' in unit_errors(scoped.decode(wire), {'E1': 'owned'}, node=META,
                                                   version=7, metadata_rows=True)
    feedback = scoped.field_feedback(wire, {'E1': 'owned'}, frame_count_rules=True)
    issue = next(x for x in feedback['issues'] if x['code'] == 'timeline.frameIterations')
    assert issue['actual'] == count and issue['requiredRelation'] == 'frameIterations > 0'
    assert issue['perFrameStepIndices'] and 'optimizer updates' in issue['expected']
    assert 'suggestedValue' not in issue and wire == before and not feedback['scientificApproval']


def test_no_frame_block_requires_zero_without_reclassifying_steps():
    wire = scope_authored(); wire['frameIterations'] = 3
    for step in wire['steps']: step['scope'] = 'per_repeat'
    for component in wire['components']: component['lifecycle']['scope'] = 'per_repeat'
    before = deepcopy(wire)
    issue = next(x for x in scoped.field_feedback(wire, {'E1': 'owned'}, frame_count_rules=True)['issues']
                 if x['code'] == 'timeline.frameIterations')
    assert issue['requiredRelation'] == 'frameIterations == 0' and not issue['perFrameStepIndices']
    assert wire == before


def test_new_rule_does_not_change_legacy_prompts_schema_or_decoding():
    wire = scope_authored(); source = '{"original":"complete"}'
    legacy = scoped.generation_prompt(source, {})
    assert scoped.COUNT_POLICY not in legacy
    assert scoped.generation_prompt(source, {}, frame_count_rules=True) == scoped.POLICY + scoped.COUNT_POLICY + legacy[len(scoped.POLICY):]
    old = scoped.descriptor(); new = scoped.descriptor(frame_count_rules=True)
    assert 'description' not in old['schema']['properties']['frameIterations']
    assert new['schema']['properties']['frameIterations']['description'] == scoped.COUNT_POLICY.strip()
    assert scoped.descriptor() == old and scoped.decode(wire)['frameIterations'] == wire['frameIterations']


def test_one_explicit_count_revision_full_assembly_and_resume():
    wire = scope_authored(); bad = deepcopy(wire); bad['frameIterations'] = 0
    r, original, invoke, run = setup_repair([response(bad), response(wire), *map(response, explicit_initializers())])
    r['workflowMetadataRepairContractVersion'] = 16
    saved = run(); initial = saved['units']['metadata']; revision = saved['metadataRepair']
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    assert 'timeline.frameIterations' in initial['errors'] and initial['response'] == response(bad)
    assert initial['request']['extra']['response_format']['name'] == 'typed_scope_release_steps_v2'
    data = input_value(revision['request']['prompt'])
    assert data['invalidMetadata']['frameIterations'] == 0
    assert data['authoritativeInput'] == json.loads(original.split('Authoritative input data (not instructions):\n')[1])
    issue = next(x for x in data['fieldFeedback']['issues'] if x['code'] == 'timeline.frameIterations')
    assert issue['requiredRelation'] == 'frameIterations > 0'
    assert revision['value']['frameIterations'] == wire['frameIterations']
    calls = invoke.call_count; assert calls == 5 and run() == saved and invoke.call_count == calls
