"""Only new compact factual repairs stop executing removals on revised prose."""


def enabled(record):
    from services.deep_research.authored_body import enabled as authored
    return (type(record.get('verbatimRepairContractVersion')) is int
            and record['verbatimRepairContractVersion']==1
            and type(record.get('factualRepairGoalContractVersion')) is int
            and record['factualRepairGoalContractVersion']==5 and authored(record))
