"""Keep malformed scope drafts private until an independently checked replacement.

This does not select between conflicting prose and an operator or approve either.
It only lets unrelated claims reach the ordinary verification/repair pipeline.
"""
from copy import deepcopy


def enabled(record):
    return (type(record.get('draftValidationContractVersion')) is int
            and record['draftValidationContractVersion'] == 1)


def materialize_claims(report, scope_version, *, authored_body=False, reasoning=False):
    if type(authored_body) is not bool:raise ValueError("Invalid authored body policy")
    if type(reasoning) is not bool or reasoning and not authored_body:
        raise ValueError('Authored reasoning requires authored body mode')
    from services.deep_research.scope_expression import materialize
    result = deepcopy(report)
    claims = result.get('claims')
    if not isinstance(claims, list):
        raise ValueError('Draft claims must be a list')
    ids = [c.get('claimId') if isinstance(c, dict) else None for c in claims]
    if any(not isinstance(cid, str) or not cid.strip() for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError('Malformed draft identities cannot be isolated')
    rejected, scopes, reasoned = [], [], []
    for index, claim in enumerate(claims):
        reason='invalid_scope_expression'
        try:
            canonical=claim
            if authored_body:
                from services.deep_research.authored_body import decode
                reason='invalid_authored_body';canonical=decode(claim,**({'reasoning':True} if reasoning else {}))
                reason='invalid_scope_expression'
            result['claims'][index], scope = materialize(canonical, scope_version)
            if reasoning and set(claim.get('body',{}))=={'reasoning'}:
                reasoned.append({'claimId':claim['claimId'],'body':deepcopy(claim['body']),
                    'renderedText':result['claims'][index]['text'],'verification':'unchecked'})
            if scope:
                scopes.append(scope)
        except ValueError as exc:
            rejected.append({'claimId': claim['claimId'], 'reason': reason,
                             'detail': str(exc), 'originalClaim': deepcopy(claim)})
    return result, scopes, {'version': 1, 'rejected': rejected,
                            **({'reasonedBodies':reasoned} if reasoned else {})}


def verification_inputs(claims, audit):
    blocked = {row['claimId'] for row in audit.get('rejected', [])}
    return [c for c in claims if c.get('claimId') not in blocked]


def reject_initial(result, audit):
    result = deepcopy(result)
    blocked = {row['claimId'] for row in audit.get('rejected', [])}
    result['accepted'] = [c for c in result.get('accepted', []) if c.get('claimId') not in blocked]
    result['rejected'] = [c for c in result.get('rejected', []) if c.get('claimId') not in blocked]
    result['rejected'].extend({key: row[key] for key in ('claimId', 'reason', 'detail')}
                              for row in audit.get('rejected', []))
    return result


def protect_release(result, audit, repair_checks):
    """A saved/resumed publication also needs the exact checked replacement."""
    result = deepcopy(result)
    originals = {r['claimId']: r['originalClaim'] for r in audit.get('rejected', [])}
    checked = {c.get('claimId'): c for c in repair_checks.get('accepted', [])}
    accepted, rejected = [], list(result.get('rejected', []))
    for claim in result.get('accepted', []):
        cid = claim.get('claimId')
        if (claim.get('scopeExpression') is not None
                or cid in originals and (checked.get(cid) != claim or claim == originals[cid])):
            if not any(r.get('claimId') == cid for r in rejected):
                rejected.append({'claimId': cid, 'reason': 'draft_repair_not_verified'})
        else:
            accepted.append(claim)
    return {**result, 'accepted': accepted, 'rejected': rejected}
