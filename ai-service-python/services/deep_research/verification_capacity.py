"""Stable, versioned request windows; the ledger still admits each call atomically.

The window must not shrink with current usage: after an interruption that would
change a settled request's digest and could submit it again. Only newly created
server-versioned runs use the larger verification window. Their total token/call
budget, protected pool, deadline and unknown-call guards remain authoritative.
"""

VERIFICATION_INPUT_BYTES = 32000
VERIFICATION_NODES = frozenset({
    'verify', 'verify_repair', 'verify_design_config', 'verify_design_science',
    'verify_repair_design_config', 'verify_repair_design_science',
})


def has_verification_input_contract(record, node):
    return (isinstance(record, dict)
            and type(record.get('verificationInputContractVersion')) is int
            and record['verificationInputContractVersion'] == 1
            and isinstance(node, str) and node in VERIFICATION_NODES)


def verification_input_limit(record, node, legacy_limit, configured_limit):
    if has_verification_input_contract(record, node):
        return min(configured_limit, VERIFICATION_INPUT_BYTES)
    return legacy_limit
