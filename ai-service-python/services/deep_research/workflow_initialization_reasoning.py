"""Frozen initialization-only thinking trial under the existing output budget.

Visible JSON remains independently validated; reasoning is never an answer.
No deadline/output increase, provider retry or non-initialization policy change.
"""
MARKER = 'workflowInitializationReasoningContractVersion'


def enabled(record):
    from services.deep_research.workflow_initialization_semantics import enabled as semantics
    return (isinstance(record, dict) and type(record.get(MARKER)) is int
            and record[MARKER] == 1 and semantics(record))
