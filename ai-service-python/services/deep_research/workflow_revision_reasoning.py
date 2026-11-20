"""Frozen semantic reasoning for the single complete metadata revision.

Same prompt/schema, input window, output reservation and deadline. Reasoning
uses the existing output allowance and never becomes an accepted answer.
"""


def enabled(record):
    from services.deep_research.workflow_revision_input import enabled as complete_input
    return (isinstance(record, dict)
            and type(record.get('workflowRevisionReasoningContractVersion')) is int
            and record['workflowRevisionReasoningContractVersion'] == 1
            and complete_input(record))
