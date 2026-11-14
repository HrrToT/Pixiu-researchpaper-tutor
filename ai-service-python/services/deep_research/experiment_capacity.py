"""Versioned experiment input windows, independent of the whole-run budget.

Reserve the maximum accepted plan before selecting evidence, so a valid plan
cannot displace its own required sources. Old runs keep their exact windows.
"""

EXPERIMENT_INPUT_BYTES = 32000
NODES = frozenset({'plan_experiment', 'synthesize'})


def enabled(record):
    from services.deep_research.experiment_generation_envelope import enabled as envelope
    return (isinstance(record, dict)
            and type(record.get('experimentInputContractVersion')) is int
            and record['experimentInputContractVersion'] == 1
            and record.get('outputKind') == 'experiment_design' and envelope(record))


def input_limit(record):
    return EXPERIMENT_INPUT_BYTES if enabled(record) else 24000


def node_input_limit(record,node):
    from services.deep_research.planning_transport import overhead_bytes
    return max(0,input_limit(record)-overhead_bytes(record,node))


def reserved_basis_bytes(record):
    from services.deep_research.experiment_planning import MAX_BASIS_BYTES, basis_limit
    if (enabled(record) and type(record.get('experimentGenerationEnvelopeContractVersion')) is int
            and record['experimentGenerationEnvelopeContractVersion'] in (2,3)):
        from services.deep_research.experiment_planning import wire_basis_limit
        return wire_basis_limit(record)
    return MAX_BASIS_BYTES if enabled(record) else basis_limit(record)


def transport_limit(record, node, legacy_limit, configured_limit):
    from services.deep_research.planning_transport import overhead_bytes
    if enabled(record) and node in NODES:
        return max(0,min(configured_limit, EXPERIMENT_INPUT_BYTES)-overhead_bytes(record,node))
    return max(0,legacy_limit-overhead_bytes(record,node))
