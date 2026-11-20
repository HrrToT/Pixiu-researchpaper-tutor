"""Initialization-only HTTP receipt observation, with no provider payload change."""
MARKER = 'workflowInitializationObservationContractVersion'


def enabled(record):
    from services.deep_research.workflow_initialization_readable import enabled as readable
    return (isinstance(record,dict) and type(record.get(MARKER)) is int
            and record[MARKER]==1 and readable(record))
