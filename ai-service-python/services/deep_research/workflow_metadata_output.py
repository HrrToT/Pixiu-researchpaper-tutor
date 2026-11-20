"""Frozen output allowance for complete symbolic workflow metadata.

The symbolic profile must not accidentally fall back to the old small default.
This changes only per-call reservation and deadline; whole-run and semantic
output limits, schemas, truncation rejection and source checks remain intact.
"""


def enabled(record):
    return (isinstance(record,dict)
            and all(type(record.get(k)) is int and record[k]==v for k,v in (
                ('workflowMetadataOutputContractVersion',1),
                ('workflowMetadataRepairContractVersion',34),
                ('executionWorkflowContractVersion',7),('structuredOutputContractVersion',15))))


def options(record,node,value):
    if enabled(record) and node in ('plan_workflow_meta','repair_workflow_meta'):
        return {**value,'max_tokens':6144,'timeout_seconds':90}
    return value
