from copy import deepcopy
import pytest

from services.deep_research.workflow_metadata_wire_feedback import complete_scaffolding, feedback
from services.deep_research.workflow_metadata_rows import encode, decode
from test_deep_research_workflow_lifecycle_units import fixtures


def test_valid_rows_keep_values_and_do_not_acquire_a_scientific_verdict():
    wire = encode(fixtures()[1]); before = deepcopy(wire)
    result = feedback(wire)
    assert result['issues'] == [] and not result['scientificApproval'] and not result['decodedProposal']
    assert wire == before


def test_complete_rows_with_bad_leaves_are_explained_without_filling_selectors():
    wire = encode(fixtures()[1])
    wire['phaseRows'][0][6] = ['baseline']
    wire['componentRows'][0][2][1] = 'baseline'
    before = deepcopy(wire)
    assert complete_scaffolding(wire)
    with pytest.raises(ValueError): decode(wire)
    result = feedback(wire); by_path = {v['path']: v for v in result['issues']}
    assert by_path['/phaseRows/0/6/0']['actual'] == 'baseline'
    assert by_path['/componentRows/0/2/1']['actual'] == 'baseline'
    assert wire == before


@pytest.mark.parametrize('change', ['root', 'extra', 'phase_arity', 'component_arity', 'nonfinite'])
def test_incomplete_or_ambiguous_scaffolding_cannot_be_presented_as_complete(change):
    wire = encode(fixtures()[1])
    if change == 'root': wire = []
    elif change == 'extra': wire['unknown'] = 'do not silently drop this'
    elif change == 'phase_arity': wire['phaseRows'][0].pop()
    elif change == 'component_arity': wire['componentRows'][0].append('extra')
    else: wire['frameIterations'] = float('nan')
    assert not complete_scaffolding(wire)
    with pytest.raises(ValueError): feedback(wire)


def test_readonly_metrics_and_output_ids_used_as_dependencies_remain_invalid():
    wire = encode(fixtures()[1]); index = next(i for i, p in enumerate(wire['phaseRows']) if p[2] == 'evaluate')
    wire['phaseRows'][index][7] = ['metric_result']
    wire['phaseRows'][index][5] = ['not_a_phase_id']
    before = deepcopy(wire); result = feedback(wire)
    assert {'wire.readonly.updates', 'wire.update.state', 'wire.phase_refs.unknown'} <= {v['code'] for v in result['issues']}
    assert wire == before
