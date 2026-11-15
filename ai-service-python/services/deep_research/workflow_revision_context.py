"""Bound a complete proposal revision without discarding its original premises.

Only new, server-frozen profiles receive this window. Token reservation and
whole-run budgets still apply before any HTTP request.
"""
MAX_INPUT = 64000
NODE = 'repair_workflow_meta'


def enabled(record):
    from services.deep_research.workflow_revision_input import enabled as revision
    from services.deep_research.workflow_metadata_planning_output import enabled as planning
    return (isinstance(record, dict)
            and type(record.get('workflowRevisionContextContractVersion')) is int
            and record['workflowRevisionContextContractVersion'] == 1
            and revision(record) and planning(record))
