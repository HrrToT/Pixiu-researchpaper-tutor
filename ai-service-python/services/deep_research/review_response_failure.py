"""Isolate a received invalid single-fact review; never infer its verdict."""
import hashlib
import json


class ResponseAudit(dict):
    """Server-created provenance, not a field trusted from a model response."""


def enabled(record):
    return (type(record.get('perClaimReviewFailureContractVersion')) is int
            and record['perClaimReviewFailureContractVersion'] == 1)


def eligible(policy, isolation, claims, result, error, node):
    return (policy is True and isolation is True and node in {'verify', 'verify_repair'}
            and len(claims) == 1 and claims[0].get('kind') in {'reported', 'inference'}
            and not claims[0].get('executionSpec') and not claims[0].get('designRole')
            and isinstance(result, dict) and not result.get('notStarted')
            and error.code == 'invalid_verification_response'
            and error.details.get('responseState') == 'received_invalid')


def unresolved(claim, result):
    content = result.get('content')
    raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
    return {'claimId': claim['claimId'], 'status': 'failed',
            'reason': '审核回复已收到但格式无效，本条尚未核验；不能据此判断论文事实或证据不足。',
            'executionState': 'received_invalid',
            'reviewResponseAudit': ResponseAudit(version=1, responseState='received_invalid',
                finishReason=result.get('finishReason'), contentSha256=hashlib.sha256(raw.encode('utf8')).hexdigest())}


def invalid(audit):
    return isinstance(audit, ResponseAudit) and audit.get('responseState') == 'received_invalid'
