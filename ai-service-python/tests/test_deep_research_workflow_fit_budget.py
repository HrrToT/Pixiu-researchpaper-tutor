from copy import deepcopy
import json
import pytest

from services.deep_research import workflow_metadata_fit_budget as typed
from services.deep_research import workflow_metadata_scope_position as scoped
from services.deep_research.workflow_units import unit_errors, META
from test_deep_research_workflow_scope_position import wire_value
from test_deep_research_workflow_metadata_ordered_integration import input_value


def test_descriptor_has_disjoint_fit_and_nonfit_budget_types_and_no_legacy_mutation():
    old = scoped.descriptor(); before = deepcopy(old)
    new = typed.descriptor(); fits = []
    for branch in new['schema']['$defs']['step']['anyOf']:
        props = branch['properties']; kind = props['kind']
        if kind.get('const') == 'fit':
            fits.append(branch)
            assert props['budget']['type'] == 'object' and 'budget' in branch['required']
        elif 'budget' in props:
            assert 'fit' not in kind.get('enum', []) and props['budget'] == {'const':None}
    assert len(fits) == 1 and scoped.descriptor() == before
    # Every previously available step kind remains expressible.
    kinds = set()
    for b in new['schema']['$defs']['step']['anyOf']:
        k=b['properties']['kind']; kinds.update(k.get('enum',[k.get('const')]))
    assert kinds == {'observe','fit','setup','evaluate','record'}


@pytest.mark.parametrize('budget', [None, {'unit':'optimizer_steps','perExecution':1.5},
    {'unit':'epochs','perExecution':True}, {'unit':'wall_seconds','perExecution':-1}])
def test_semantic_checker_still_rejects_invalid_authored_budgets_without_filling_them(budget):
    wire = wire_value(); wire['steps'][0]['budget'] = budget; before=deepcopy(wire)
    assert typed.decode(wire) == scoped.decode(wire)
    assert 'timeline.phase.budget' in unit_errors(
        typed.decode(wire), {'E1':'owned'}, node=META, version=7, metadata_rows=True)
    assert wire == before


def test_full_authoritative_input_invalid_values_and_count_obligations_remain_in_prompt():
    wire=wire_value(); wire['steps'][0]['budget']=None
    source={'question':'Original question','sources':[{'id':'E1','quote':'Full quote'}]}
    feedback=typed.field_feedback(wire,{'E1':'owned'})
    prompt=typed.revision_prompt(json.dumps(source),wire,feedback)
    assert input_value(prompt)=={'authoritativeInput':source,'invalidMetadata':wire,'fieldFeedback':feedback}
    for requirement in ('nonboolean integer >0 iff', 'per_frame steps, else 0', 'exclude baseline',
        'updates/epochs/step count/measured placeholders', 'guess missing data', 'ONE execution',
        'frameIterations times', 'repeat fits once', 'not multiplying frame count by steps/arms'):
        assert requirement in prompt
