"""Deterministic bounded repair scheduling; no model or source access."""


def split_repair_targets(claims):
    """Keep linked hypotheses and analyses together within at most three batches.

    Configuration is chosen first, scientific decisions and their limits second,
    execution last. Every original target occurs once; sibling drafts remain
    available as unverified context in each prepared request.
    """
    config, science, execution = [], [], []
    for claim in claims:
        role = claim.get('designRole')
        bucket = (config if role in {'data', 'budget', 'metrics'}
                  else science if role in {'hypothesis', 'analysis', 'limits'} else execution)
        bucket.append(claim['claimId'])
    groups = [bucket for bucket in (config, science, execution) if bucket]
    canonical_pair = any(c.get('workflowContractVersion') == 4
                         and c.get('executionSpec', {}).get('refs', {}).get('controls') in execution
                         for c in claims if isinstance(c.get('executionSpec'), dict))
    if len(groups) == 1 and len(claims) > 1 and not science and not canonical_pair:
        # Generic factual repairs can split, but a scientific decision group
        # must remain atomic even when it alone exceeds request capacity.
        width = (len(claims) + 2) // 3
        groups = [[c['claimId'] for c in claims[i:i + width]]
                  for i in range(0, len(claims), width)]
    return groups
