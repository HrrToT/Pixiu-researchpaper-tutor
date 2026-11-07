"""Keep query routing separate from source-specific research requirements."""


def eligible_obligation_ids(source, obligations):
    """Return plan targets this already-authorized source may inform.

    source.obligationIds records which query found the passage. It is not a
    material authorization or a relevance verdict. Explicit requiredSources
    still limit a target to its exact work/version/owner; unrelated-paper
    coverage must never be inherited from a successful query elsewhere.
    """
    identities = {source[key] for key in ('workId', 'versionId', 'ownerMaterialId')
                  if isinstance(source.get(key), str) and source[key]}
    return [identity for identity, obligation in obligations.items()
            if not obligation.get('requiredSources') or identities.intersection(obligation['requiredSources'])]
