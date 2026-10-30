"""Diagnostic pointers never become a corrected proposal or scientific verdict."""
from copy import deepcopy
import pytest

from services.deep_research.workflow_metadata_feedback import feedback
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_lifecycle_units import fixtures


def test_complete_valid_metadata_has_no_diagnostic_and_never_gets_approval():
    meta = fixtures()[1]
    before = deepcopy(meta)
    result = feedback(meta, {'E1': 'owned'})
    assert result['codes'] == result['issues'] == [] and not result['scientificApproval']
    assert meta == before
    assert result['declaredPhaseIds'] == [p['phaseId'] for p in meta['phases']]


def test_malformed_lifecycle_still_explains_independent_unknown_phase_references():
    meta = fixtures()[1]
    meta['components'][0]['lifecycle']['createAfter'] = 'baseline'
    meta['components'][0]['lifecycle']['disposeAfter'] = 'after_record'
    meta['phases'][1]['after'] = ['after_stage1']
    before = deepcopy(meta)
    result = feedback(meta, {'E1': 'owned'})
    by_path = {v['path']: v for v in result['issues'] if 'expected' in v}
    assert by_path['/components/0/lifecycle/createAfter']['actual'] == 'baseline'
    assert by_path['/components/0/lifecycle/disposeAfter']['actual'] == 'after_record'
    assert by_path['/phases/1/after/0']['actual'] == 'after_stage1'
    assert result['codes'] == unit_errors(meta, {'E1': 'owned'}, node=META, version=7, metadata_rows=True)
    assert meta == before and not result['scientificApproval']
    result['issues'][0]['path'] = 'mutation'
    assert meta == before


def test_readonly_metric_writes_are_explained_without_moving_them_to_outputs():
    meta = fixtures()[1]
    index = next(i for i, p in enumerate(meta['phases']) if p['kind'] == 'evaluate')
    meta['phases'][index]['updates'] = ['new_psnr']
    before = deepcopy(meta)
    result = feedback(meta, {'E1': 'owned'})
    assert any(v['code'] == 'metadata.readonly.updates' for v in result['issues'])
    assert any(v['code'] == 'metadata.update.unknown' for v in result['issues'])
    assert meta == before and 'timeline.phase.evaluation_updates' in result['codes']


@pytest.mark.parametrize('item,code', [
    ({'state': 'unowned_metric', 'selector': 'value'}, 'metadata.read.unknown_state'),
    ({'phaseId': 'not_declared', 'outputId': 'metric', 'selector': 'value'}, 'metadata.read.unknown_phase'),
    ('not_a_reference_object', 'metadata.read.fields')])
def test_missing_read_references_are_explained_even_when_lifecycle_types_are_invalid(item, code):
    meta = fixtures()[1]
    meta['components'][0]['lifecycle']['createAfter'] = 'invalid_scalar'
    meta['phases'][0]['reads'] = [item]
    before = deepcopy(meta)
    result = feedback(meta, {'E1': 'owned'})
    assert any(v['code'] == code for v in result['issues'])
    assert meta == before and not result['scientificApproval']


@pytest.mark.parametrize('mutation', ['not_object', 'missing', 'component', 'phase', 'after_type'])
def test_incomplete_objects_are_rejected_without_fabricating_replacement_fields(mutation):
    meta = fixtures()[1]
    if mutation == 'not_object': meta = None
    elif mutation == 'missing': del meta['phases']
    elif mutation == 'component': meta['components'] = [None]
    elif mutation == 'phase': meta['phases'] = [None]
    else: meta['phases'][0]['after'] = None
    before = deepcopy(meta)
    result = feedback(meta, {'E1': 'owned'})
    assert result['codes'] and not result['scientificApproval'] and meta == before
