"""Small complete factual requests; per-target decisions remain independent."""
from services.deep_research.contracts import DeepResearchError
from services.deep_research.review_response_failure import unresolved

MARKER = 'comparisonReviewBatchContractVersion'
MAX_TARGETS = 3


def enabled(record):
    from services.deep_research.comparison_intent import operations_enabled
    return (operations_enabled(record) and type(record.get(MARKER)) is int
            and record[MARKER] == 1 and type(record.get('claimIsolationContractVersion')) is int
            and record['claimIsolationContractVersion'] == 1)


def groups(claims, preview):
    """Stable greedy packing with complete input previews, never time-dependent.

    Oversized singletons stay present: ordinary capacity guards report them
    unresolved without sending. No fact or source is removed to make a fit.
    """
    result=[]; current=[]
    for claim in claims:
        candidate=[*current,claim]
        if len(candidate)>MAX_TARGETS:
            result.append(current);current=[claim];continue
        measured=preview(candidate)
        if (not isinstance(measured,dict) or any(type(measured.get(k)) is not int
                or measured[k]<0 for k in ('inputBytes','maxInputBytes'))):
            raise ValueError('Invalid factual batch preview')
        if current and measured['inputBytes']>measured['maxInputBytes']:
            result.append(current);current=[claim]
        else:
            current=candidate
    if current:result.append(current)
    return result


def decode_targets(rows, claims, result, decode_one):
    """Quarantine a missing/duplicate/malformed target, with no new request.

    Foreign identities or an unreadable/truncated root cannot be assigned
    safely, so every target remains unresolved. Raw replies stay in the call
    journal; no model-controlled error text becomes a scientific correction.
    """
    targets={c['claimId']:c for c in claims}
    if (result.get('finishReason')=='length' or not isinstance(rows,list)
            or any(not isinstance(v,dict) or not isinstance(v.get('claimId'),str)
                   or v['claimId'] not in targets for v in rows)):
        return [],{key:unresolved(c,result) for key,c in targets.items()}
    valid=[]; invalid={}
    for key,claim in targets.items():
        own=[v for v in rows if v['claimId']==key]
        if len(own)!=1:
            invalid[key]=unresolved(claim,result);continue
        try:
            decoded=decode_one(own,claim)
        except DeepResearchError as exc:
            if exc.code!='invalid_verification_response' or exc.details.get('responseState')!='received_invalid':
                raise
            invalid[key]=unresolved(claim,result);continue
        if (not isinstance(decoded,list) or len(decoded)!=1 or not isinstance(decoded[0],dict)
                or decoded[0].get('claimId')!=key):
            invalid[key]=unresolved(claim,result);continue
        valid.extend(decoded)
    return valid,invalid
