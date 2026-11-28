"""A bounded input window for complete metadata and its atomic premises.

Only new experiment runs opt in. No quote or required scientific part is
removed to fit; admission still reserves the complete input and output cost.
"""
MAX_INPUT = 40000
NODE = 'plan_workflow_meta'


def enabled(record):
    from services.deep_research.workflow_metadata_envelope import enabled as output_envelope
    from services.deep_research.workflow_premises import enabled as premise_allocation
    return (isinstance(record, dict)
            and type(record.get('workflowMetadataInputContractVersion')) is int
            and record['workflowMetadataInputContractVersion'] == 1
            and output_envelope(record) and premise_allocation(record))


def input_limit(record, node):
    return MAX_INPUT if node == NODE and enabled(record) else 32000
