"""Typed fit/non-fit budgets; semantic validation and authored values unchanged."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_scope_position as scoped

NAME = 'typed_fit_budget_steps_v1'
COUNT_POLICY = (
    'frameIterations counts processed frames per repeat/arm: nonboolean integer >0 iff '
    'per_frame steps, else 0. Match the window; exclude baseline preparation. Never '
    'substitute updates/epochs/step count/measured placeholders or guess missing data. '
    'Fit perExecution is ONE execution: frame fits run frameIterations times, repeat fits '
    'once. Group budgets include these executions, not multiplying frame count by steps/arms.\n'
)

# These are deliberately the original semantic decoder and diagnostics. A
# well-typed response still needs every lifecycle and scientific check.
decode = scoped.decode
complete_scaffolding = scoped.complete_scaffolding
field_feedback = scoped.field_feedback


def generation_prompt(source_data, context):
    from services.deep_research.workflow_metadata_input import input_text
    return scoped.POLICY + COUNT_POLICY + input_text({
        'authoritativeInput': json.loads(source_data), 'unitContext': context})


def revision_prompt(source_data, value, feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return scoped.POLICY + COUNT_POLICY + 'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n' + input_text({
        'authoritativeInput': json.loads(source_data), 'invalidMetadata': value, 'fieldFeedback': feedback})


def descriptor():
    result = scoped.descriptor(); result['name'] = NAME
    definitions = result['schema']['$defs']; branches = []
    for branch in definitions['step']['anyOf']:
        props = branch['properties']; kind = props['kind']
        if 'fit' in kind.get('enum', []):
            fit = deepcopy(branch)
            # The inherited conditional only concerns evaluate, which this
            # branch cannot represent. Keep it on the remaining non-fit branch.
            fit.pop('allOf', None)
            fit['properties']['kind'] = {'const': 'fit'}
            fit['properties']['budget'] = deepcopy(next(
                b for b in props['budget']['anyOf'] if b.get('type') == 'object'))
            branches.append(fit)
            props['kind'] = {'enum': [k for k in kind['enum'] if k != 'fit']}
            props['budget'] = {'const': None}
        elif 'budget' in props:
            props['budget'] = {'const': None}
        branches.append(branch)
    definitions['step']['anyOf'] = branches
    # Exact shared property schemas, not removal of fields or constraints.
    # These two repeated structures offset the new discriminated fit branch.
    for field, name in (('outputs', 'stepOutputs'), ('reads', 'stepReads')):
        choices = [b['properties'][field] for b in branches if field in b['properties']]
        shared = max(choices, key=lambda candidate: sum(candidate == v for v in choices))
        for branch in branches:
            if branch['properties'].get(field) == shared:
                branch['properties'][field] = {'$ref': '#/$defs/' + name}
        definitions[name] = shared
    return result
