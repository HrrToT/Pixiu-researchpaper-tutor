"""Server-rendered access labels are metadata, never scientific answer text."""
import hashlib
import json
import re


def answer_display_metadata(claims, evidence):
    from services.deep_research.reporting import source_access_summary
    summary = source_access_summary(claims, evidence)
    return {'sourceAccessSummary': summary} if summary else {}


def display_metadata_digest(claims, evidence):
    refs = {ref for claim in claims for ref in claim.get('evidenceRefs', [])}
    rows = [{key: row.get(key) for key in ('evidenceId', 'sourceKind', 'accessLevel')}
            for row in evidence if row.get('evidenceId') in refs]
    value = [answer_display_metadata(claims, evidence), sorted(rows, key=lambda row: str(row['evidenceId']))]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def requests_access_level(excerpt):
    """Guard typed metadata against a request excerpt containing no access task.

    This lexical boundary does not establish semantic completeness; the
    independent reviewer still decides which answer requirements are essential.
    """
    if not isinstance(excerpt, str):
        return False
    abstract = re.search(r'摘要|\babstract\b', excerpt, re.I)
    fulltext = re.search(r'全文|\bfull[ -]?text\b|\bfull paper\b', excerpt, re.I)
    if abstract and fulltext:
        return True
    if re.search(r'访问范围|阅读范围|获取范围|access[ -]?level|access scope', excerpt, re.I):
        return True
    return bool((abstract or fulltext) and re.search(
        r'实际|取得|获取|读到|读了|标明|写明|说明|\b(?:state|specify|acquired|obtained|accessed)\b', excerpt, re.I))


def display_binding_supported(binding, known_claims, metadata):
    summary = metadata.get('sourceAccessSummary') if isinstance(metadata, dict) else None
    return (isinstance(binding, dict) and binding.get('field') == 'sourceAccessSummary'
            and 'referenceError' not in binding and isinstance(summary, str) and bool(summary)
            and binding.get('excerpt') == summary and isinstance(binding.get('claimId'), str)
            and isinstance(known_claims.get(binding['claimId']), dict))


def revalidate_display_metadata(audit, claims, evidence):
    """A resumed publication cannot inherit access checks for different labels."""
    previous = audit.get('displayMetadataDigest')
    if previous is None or previous == display_metadata_digest(claims, evidence):
        return audit
    identity = audit.get('wholeQuestionId') or 'answer_source_access'
    gap = {'obligationId': identity, 'stage': 'answer', 'wholeQuestion': True,
           'missingEvidence': '引用材料或访问范围已变化，需要重新核对来源标注'}
    return {**audit, 'status': 'invalidated_display_metadata', 'gaps': [*audit.get('gaps', []), gap]}
