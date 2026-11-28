from copy import deepcopy
import pytest

from services.deep_research.workflow_metadata_actions import encode
from services.deep_research.workflow_metadata_semantics import field_feedback
from test_deep_research_workflow_lifecycle_units import fixtures
from test_deep_research_workflow_metadata_repair import setup_repair, response


@pytest.mark.parametrize('budget', [None, {'unit':'optimizer_steps','perExecution':True},
    {'unit':'epochs','perExecution':1.5}, {'unit':'wall_seconds','perExecution':-1}])
def test_budget_diagnostics_point_to_original_field_without_selecting_a_cap(budget):
    meta = fixtures()[1]; meta['phases'][0]['budget'] = budget
    wire = encode(meta); before = deepcopy(wire)
    feedback = field_feedback(wire, {'E1':'owned'})
    issue = next(x for x in feedback['issues'] if x['code']=='timeline.phase.budget')
    assert issue['path']=='/phaseRows/0/10' and issue['actual']==budget and issue['actualPresent']
    assert 'fit needs' in issue['expected']
    assert wire == before and not feedback['scientificApproval']


def test_lifetime_use_is_explained_even_while_bad_budget_blocks_canonical_graph_checks():
    meta = fixtures()[1]; meta['phases'][0]['budget'] = None
    meta['components'][0]['lifecycle']['createAfter'] = ['stage1']
    wire = encode(meta); before = deepcopy(wire)
    issues = field_feedback(wire, {'E1':'owned'})['issues']
    assert any(x['code']=='timeline.phase.budget' for x in issues)
    uses = [x for x in issues if x['code']=='wire.lifecycle.before_creation']
    assert {x['path'] for x in uses} == {'/phaseRows/0/6/1','/phaseRows/0/7/0'}
    assert next(x for x in uses if x['path']=='/phaseRows/0/6/1')['actual'] == wire['phaseRows'][0][6][1]
    assert all(x['componentId']=='ntc' and x['createAfter']==['stage1'] for x in uses)
    assert wire == before


def test_valid_timeline_has_no_extra_findings_or_scientific_approval():
    wire = encode(fixtures()[1]); before = deepcopy(wire)
    result = field_feedback(wire, {'E1':'owned'})
    assert not result['issues'] and not result['codes'] and not result['scientificApproval']
    assert wire == before


def test_bad_action_is_not_filled_to_make_a_canonical_diagnosis_possible():
    wire = encode(fixtures()[1]); wire['phaseRows'][0][9] = ['a', [], ['b', []]]
    before = deepcopy(wire); result = field_feedback(wire, {'E1':'owned'})
    assert any(x['code']=='wire.operation.object' for x in result['issues'])
    assert wire == before and not result['scientificApproval']


def test_one_model_revision_of_missing_fit_budget_is_bound_to_original_then_resumes():
    _, meta, inits = fixtures(); bad = deepcopy(meta); bad['phases'][0]['budget'] = None
    r, _, invoke, run = setup_repair([response(encode(bad)),response(encode(meta)),*map(response,inits)])
    r['workflowMetadataRepairContractVersion'] = 7
    result = run()
    assert result['units']['metadata']['value']['phases'][0]['budget'] is None
    assert result['metadataRepair']['version']==7 and result['metadataRepair']['status']=='ready'
    calls = invoke.call_count
    assert run()==result and invoke.call_count==calls and not result['scientificApproval']
