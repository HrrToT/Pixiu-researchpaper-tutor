"""Preserve failed design definitions as context, never as evidence or approval."""
from collections import Counter
from copy import deepcopy


def enabled(version):
    return type(version) is int and version in (2,3,4,5,6,7,8,9)


def rejected_context(claims, rejections, *, exclude=(), phase='precheck'):
    counts=Counter(c.get('claimId') for c in claims if isinstance(c,dict)
        and isinstance(c.get('claimId'),str))
    excluded=set(exclude)
    checks={}
    for row in rejections:
        if isinstance(row,dict) and isinstance(row.get('claimId'),str):
            checks.setdefault(row['claimId'],[]).append(deepcopy(row))
    context=[]
    for claim in claims:
        if (not isinstance(claim,dict) or not isinstance(claim.get('claimId'),str)
                or counts[claim['claimId']]!=1 or claim['claimId'] in excluded
                or claim['claimId'] not in checks
                or claim.get('kind') not in {'proposal','suggestion','hypothesis'}
                or type(claim.get('designContractVersion')) is not int
                or claim['designContractVersion']!=2):
            continue
        row=deepcopy(claim)
        # Server-owned annotation overwrites any untrusted draft annotation.
        row['reviewContextState']={'status':'rejected','phase':phase,
            'checks':checks[claim['claimId']]}
        context.append(row)
    return context
