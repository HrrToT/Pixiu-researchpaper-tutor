"""Repair input3 supplies the writable schema missing from the brief envelope.

Only trusted instructions change. Frozen input1/2 requests retain their bytes;
target values, source permissions and evidence fitting remain untouched.
"""
from services.deep_research.experiment_repair_input_brief import render as brief
from services.deep_research.experiment_template import grammar_for_roles
from services.deep_research.experiment_execution_guidance import initialization_grammar


def render(**kwargs):
    roles = {claim['designRole'] for claim in kwargs['targets']}
    grammar = initialization_grammar(grammar_for_roles(roles,
        workflow_version=5 if any(c.get('workflowContractVersion')==5 for c in kwargs['targets']) else 4),
        {'experimentExecutionGuidanceContractVersion': 2})
    return (brief(**kwargs) + '\nWritable role grammar (replacement objects must be complete):\n'
        + grammar)
