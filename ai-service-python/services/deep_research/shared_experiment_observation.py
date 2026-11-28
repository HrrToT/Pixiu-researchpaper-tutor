"""Opt-in safe HTTP receipt phases, frozen independently of scientific policy."""
MARKER='sharedExperimentHttpObservationContractVersion'
NODES=frozenset({'plan_experiment_shared','review_experiment_shared','repair_experiment_shared'})


def enabled(record,node):
    from services.deep_research.shared_experiment_generation import enabled as shared_enabled
    return (isinstance(node,str) and node in NODES and shared_enabled(record)
            and type(record.get(MARKER)) is int and record[MARKER]==1)
