"""Deterministic bounded repair scheduling; no model or source access."""


def split_repair_targets(claims, *, scientific_metrics=False,structural_priority=False,rejections=()):
    """Keep linked hypotheses and analyses together within at most three batches.

    Configuration is chosen first, scientific decisions and their limits second,
    execution last. Every original target occurs once; sibling drafts remain
    available as unverified context in each prepared request.
    Policy 2 keeps metrics with the scientific decision they operationalize.
    """
    config, science, execution = [], [], []
    for claim in claims:
        role = claim.get('designRole')
        bucket = (science if scientific_metrics and role == 'metrics'
                  else config if role in {'data', 'budget', 'metrics'}
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
    if structural_priority is True:
        hard={'incomplete_execution_spec','incomplete_experiment_workflow','incomplete_experiment_protocol',
            'incomplete_budget_spec','incomplete_hypothesis_spec','invalid_workflow_contract',
            'invalid_protocol_contract','invalid_budget_contract','invalid_hypothesis_contract'}
        # Stable sort preserves all atomic groups and legacy order on ties.
        # Structural failures are server prechecks, never a free-text model rank.
        blocked={r['claimId'] for r in rejections if isinstance(r,dict) and isinstance(r.get('claimId'),str)
            and isinstance(r.get('reason'),str) and r['reason'] in hard}
        groups=sorted(groups,key=lambda group:0 if any(cid in blocked for cid in group) else 1)
    return groups
