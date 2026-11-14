"""Normalize locally reused model labels before a fresh plan is persisted."""
from collections import Counter
from copy import deepcopy
import hashlib
import json


def normalize_generated_obligation_ids(items):
    """Disambiguate only cross-item labels; preserve every substantive field.

    Generated plans reference dependencies by itemId, never obligationId.
    At this boundary no evidence or saved coverage references these new labels.
    Existing plans and same-item duplicate obligations still require validation;
    this helper must not rescue malformed identities or merge distinct questions.
    """
    result = deepcopy(items)
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        return result, []
    item_ids = [item.get('itemId') for item in result]
    if (any(not isinstance(identity, str) or not identity or len(identity) > 128 for identity in item_ids)
            or len(set(item_ids)) != len(item_ids)):
        return result, []
    counts = Counter()
    for item in result:
        obligations = item.get('obligations')
        if not isinstance(obligations, list) or any(not isinstance(row, dict) for row in obligations):
            return result, []
        labels = [row.get('obligationId') for row in obligations]
        if (any(not isinstance(identity, str) or not identity or len(identity) > 128 for identity in labels)
                or len(set(labels)) != len(labels)):
            return result, []
        counts.update(labels)
    used = set(counts)
    changes = []
    for item in result:
        for obligation in item['obligations']:
            original = obligation['obligationId']
            if counts[original] <= 1:
                continue
            token = hashlib.sha256(json.dumps([item['itemId'], original],
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
            candidate = 'ob_' + token
            suffix = 0
            while candidate in used:
                suffix += 1
                candidate = 'ob_' + token + '_' + str(suffix)
            used.add(candidate)
            obligation['obligationId'] = candidate
            changes.append({'itemId': item['itemId'], 'originalObligationId': original,
                            'obligationId': candidate})
    return result, changes
