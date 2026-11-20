"""Preserve completed semantic decisions when a later batch is not admitted."""
from copy import deepcopy
import hashlib
import json

from services.deep_research.contracts import BudgetExhaustedError


class InitialReviewBudgetStop(BudgetExhaustedError):
    def __init__(self, cause, verdicts):
        super().__init__(cause.details['kind'], cause.details['limit'], cause.details['used'])
        self.verdicts = deepcopy(verdicts)


def input_digest(claims, evidence, proposal_context):
    payload = json.dumps([claims, evidence, proposal_context], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf8')).hexdigest()


def stopped_verdicts(claims, completed):
    by_id = {row['claimId']: row for row in completed}
    return [deepcopy(by_id[c['claimId']]) if c['claimId'] in by_id else {
        'claimId': c['claimId'], 'status': 'failed', 'executionState': 'not_started',
        'reason': '预算准入停止，尚未完成本条审核；不能据此判断论文事实或证据不足。',
    } for c in claims]
