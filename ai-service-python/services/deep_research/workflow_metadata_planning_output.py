"""Visible-output reservation for complete first-pass metadata only.

Keeps the same prompt, schema, deadline, output byte caps and whole-run limits.
Legacy requests and the single revision allowance retain their exact policy.
"""
NODE = 'plan_workflow_meta'
MAX_OUTPUT = 8192


def enabled(record):
    from services.deep_research.workflow_metadata_window import enabled as complete_input
    return (isinstance(record, dict)
            and type(record.get('workflowMetadataPlanningOutputContractVersion')) is int
            and record['workflowMetadataPlanningOutputContractVersion'] == 1
            and complete_input(record))


def options(record, node, value):
    return {**value, 'max_tokens': MAX_OUTPUT} if node == NODE and enabled(record) else value
