"""Source-first wording for one editable target alongside fixed points."""


def one_editable(report, protected_ids):
    claims = report.get('claims') if isinstance(report, dict) else None
    if (not isinstance(claims, list) or not claims
            or not isinstance(protected_ids, (tuple, list)) or not protected_ids
            or any(not isinstance(k, str) or not k for k in protected_ids)):
        return False
    ids = [c.get('claimId') if isinstance(c, dict) else None for c in claims]
    if (any(not isinstance(k, str) or not k for k in ids) or len(set(ids)) != len(ids)
            or len(set(protected_ids)) != len(protected_ids) or not set(protected_ids) <= set(ids)):
        return False
    return len(set(ids) - set(protected_ids)) == 1


def enabled(record, report, protected_ids):
    from services.deep_research.audience_edit_budget import enabled as budgeted
    return (type(record.get('audienceEditableSourceContractVersion')) is int
            and record['audienceEditableSourceContractVersion'] == 1
            and budgeted(record) and one_editable(report, protected_ids))


def validate(report, protected_ids, contract_version, protected_edits, source_first_single):
    if (contract_version != 9 or protected_edits is not True or source_first_single is not False
            or not one_editable(report, protected_ids)):
        raise ValueError('Source-first editable reader requires exactly one editable contract9 target and fixed points')
