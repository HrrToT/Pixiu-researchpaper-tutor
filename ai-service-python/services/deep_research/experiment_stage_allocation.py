"""Select original premises against the request actually sent at this stage.

This does not admit a larger request or approve a scientific decision. The
generation envelope still rechecks the actual decision and workflow together.
"""


def enabled(record):
    from services.deep_research.experiment_capacity import enabled as capacity
    from services.deep_research.scientific_outline import enabled as outline
    return (isinstance(record, dict)
            and type(record.get('experimentStageAllocationContractVersion')) is int
            and record['experimentStageAllocationContractVersion'] == 1
            and capacity(record) and outline(record))
