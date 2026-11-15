"""Bound complete metadata revision context separately from initial planning.

Revision includes the original proposal and diagnostics as well as all original
premises. This never changes source selection, response checks or run budgets.
"""
MAX_INPUT = 40000
NODE = 'repair_workflow_meta'


def enabled(record):
    from services.deep_research.workflow_metadata_envelope import enabled as envelope
    return (isinstance(record, dict)
            and type(record.get('workflowRevisionInputContractVersion')) is int
            and record['workflowRevisionInputContractVersion'] == 1 and envelope(record))


def input_limit(record):
    return MAX_INPUT if enabled(record) else 32000
