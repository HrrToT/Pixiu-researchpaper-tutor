"""Request fitting is advisory; the ledger still reserves atomically."""
REPAIR_OUTPUT_TOKENS = 8192
FRAMING_TOKENS = 1024


def repair_prompt_byte_limit(budget):
    if not budget or 'maxTokens' not in budget:
        return 24000
    keys = ('maxTokens', 'reserveTokens', 'tokens', 'normalTokens')
    values = [budget.get(key, 0) for key in keys]
    if any(type(value) is not int or value < 0 for value in values):
        return 0
    maximum, reserve, total_used, normal_used = values
    remaining = min(maximum - total_used, maximum - reserve - normal_used)
    return max(0, min(24000, remaining - REPAIR_OUTPUT_TOKENS - FRAMING_TOKENS))
