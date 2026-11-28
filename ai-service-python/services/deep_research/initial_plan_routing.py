"""Server-owned initial orchestration route; never a failed-request fallback."""


def uses_routine_model(record,node):
    return (node=='plan' and type(record.get('initialPlanModelContractVersion')) is int
            and record['initialPlanModelContractVersion']==1)
