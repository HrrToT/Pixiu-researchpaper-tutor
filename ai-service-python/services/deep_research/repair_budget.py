"""Request fitting is advisory; the ledger still reserves atomically."""
REPAIR_OUTPUT_TOKENS = 8192
FRAMING_TOKENS = 1024
REPAIR_INPUT_BYTES = 24000


def repair_exploration_headroom(normal_pool, allocation_version=0):
    """Protect one full repair request while retaining exploration capacity.

    Small custom pools keep at least one third for exploration; the repair
    fitter still refuses requests that cannot fit the remaining actual budget.
    """
    if type(allocation_version) is int and allocation_version == 1:
        # Finalization already has its own isolated reserve. Allocate three
        # fifths of the NORMAL pool to acquisition and two fifths to repair.
        # This is an allocation target, not a promise that a full 24KB repair
        # fits. The actual repair fitter and transactional total limits still
        # reject any request that exceeds its complete reservation envelope.
        return min(REPAIR_INPUT_BYTES + REPAIR_OUTPUT_TOKENS + FRAMING_TOKENS,
                   max(0, normal_pool) * 2 // 5)
    return min(REPAIR_INPUT_BYTES + REPAIR_OUTPUT_TOKENS + FRAMING_TOKENS,
               max(0, normal_pool) * 2 // 3)


def repair_prompt_byte_limit(budget, output_tokens=REPAIR_OUTPUT_TOKENS, *, input_bytes=REPAIR_INPUT_BYTES):
    if type(input_bytes) is not int or input_bytes not in (24000, 32000):
        return 0
    if type(output_tokens) is not int or not 1 <= output_tokens <= REPAIR_OUTPUT_TOKENS:
        return 0
    if not budget or 'maxTokens' not in budget:
        return input_bytes
    keys = ('maxTokens', 'reserveTokens', 'tokens', 'normalTokens')
    values = [budget.get(key, 0) for key in keys]
    if any(type(value) is not int or value < 0 for value in values):
        return 0
    maximum, reserve, total_used, normal_used = values
    remaining = min(maximum - total_used, maximum - reserve - normal_used)
    return max(0, min(input_bytes, remaining - output_tokens - FRAMING_TOKENS))


def repair_batch_output_limit(target_count):
    """Smaller target batches need less output reservation, never a larger cap."""
    return min(REPAIR_OUTPUT_TOKENS, max(4096, 1024 * (target_count + 1)))


def repair_output_options(options):
    result = dict(options)
    maximum = result.pop('_repair_output_limit', REPAIR_OUTPUT_TOKENS)
    if type(maximum) is not int or not 1 <= maximum <= REPAIR_OUTPUT_TOKENS:
        raise ValueError('Invalid server repair output limit')
    return {**result, 'max_tokens': maximum}


def experiment_repair_window(record):
    """Only the frozen, fully specified experimental repair4 may use 32KB."""
    from services.deep_research.experiment_repair import enabled
    return (isinstance(record, dict) and enabled(record)
            and type(record.get('experimentRepairInputContractVersion')) is int
            and record['experimentRepairInputContractVersion'] == 4
            and record.get('experimentRepairContractVersion') == 6
            and type(record.get('structuredOutputContractVersion')) is int
            and record['structuredOutputContractVersion'] in (8,9,10,11,12,13,14,15))
