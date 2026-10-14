"""Freeze requested answer requirements before synthesis; audit their bindings.

This is an identity/completeness contract, not a semantic proof. The reviewer
still has to judge whether an excerpt explains the requested relationship.
"""
import hashlib
import json
from services.deep_research.answer_coverage import _bindings_supported, _known_claims_by_id

RESPONSE_TYPES = {'identification', 'explanation', 'procedure', 'limitation'}


def validate_completion_criteria(plan, *, required=False):
    for item in plan:
        for obligation in item.get('obligations', []):
            criteria = obligation.get('completionCriteria')
            if criteria is None and not required:
                continue
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 4:
                raise ValueError('Each obligation needs one to four completion criteria')
            identities = set()
            for criterion in criteria:
                if not isinstance(criterion, dict):
                    raise ValueError('Invalid completion criterion')
                key = criterion.get('criterionId')
                description = criterion.get('requirement')
                if (not isinstance(key, str) or not key or len(key) > 128 or key in identities
                        or not isinstance(description, str) or not description.strip() or len(description) > 500
                        or not isinstance(criterion.get('responseType'), str)
                        or criterion['responseType'] not in RESPONSE_TYPES):
                    raise ValueError('Invalid completion criterion')
                identities.add(key)
    return plan


def completion_criteria_gaps(plan, claims, verdicts):
    """Missing, duplicate, downgraded or unbound criterion verdicts stay open.

    Only covered obligations are examined here: ordinary partial/missing
    decisions already have their gaps. Never accept a model-written replacement
    criterion or use a source quotation as the answer binding.
    """
    known = _known_claims_by_id(claims)
    result = {}
    for item in plan:
        for obligation in item.get('obligations', []):
            criteria = obligation.get('completionCriteria')
            if criteria is None:
                continue
            identity = obligation.get('obligationId')
            matches = [v for v in verdicts if isinstance(v, dict) and v.get('obligationId') == identity]
            if len(matches) != 1 or matches[0].get('status') != 'covered':
                continue
            rows = matches[0].get('criteria')
            rows = rows if isinstance(rows, list) else []
            expected = {c['criterionId'] for c in criteria}
            unknown = any(not isinstance(row, dict) or not isinstance(row.get('criterionId'), str)
                          or row['criterionId'] not in expected for row in rows)
            missing = []
            for criterion in criteria:
                found = [row for row in rows if isinstance(row, dict)
                         and row.get('criterionId') == criterion['criterionId']]
                if (unknown or len(found) != 1 or found[0].get('status') != 'covered'
                        or found[0].get('responseType') != criterion['responseType']
                        or not _bindings_supported(found[0].get('bindings'), known)):
                    missing.append(criterion['requirement'])
            if missing:
                result[identity] = missing
    return result


def completion_contract_digest(plan, claims):
    requirements = [{key: o.get(key) for key in ('obligationId', 'question', 'requiredSources', 'completionCriteria')}
                    for item in plan for o in item.get('obligations', []) if 'completionCriteria' in o]
    if not requirements:
        return None
    answers = [{key: c.get(key) for key in ('claimId', 'text', 'conditions', 'evidenceRefs')}
               for c in claims]
    return hashlib.sha256(json.dumps([requirements, answers], ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def revalidate_completion_audit(plan, claims, audit):
    current = completion_contract_digest(plan, claims)
    if current is None:
        return audit
    missing = completion_criteria_gaps(plan, claims, audit.get('verdicts', []))
    if current == audit.get('completionContractDigest') and not missing:
        return audit
    # Changed requirements/answer cannot inherit a successful older semantic
    # decision. Keep saved content, leave explicit gaps and never invoke models.
    gaps = [{'obligationId': o['obligationId'], 'question': o['question'], 'stage': 'answer',
             'missingEvidence': '回答要求或内容已变化，需要重新核对完成情况',
             'missingAspects': [c['requirement'] for c in o['completionCriteria']]}
            for item in plan for o in item.get('obligations', []) if o.get('completionCriteria')]
    return {**audit, 'status': 'invalidated_completion_contract', 'gaps': [*audit.get('gaps', []), *gaps]}


CRITERIA_GUIDANCE = '''Each obligation also needs completionCriteria: 1-4 objects
{criterionId, requirement, responseType}. IDs are unique within the obligation;
responseType is identification, explanation, procedure or limitation.
Fix the minimal requested answer BEFORE seeing a draft. For a how/why mechanism
question, use explanation criteria for the requested relationships: specify
which input acts on which operation/output and what the reader should understand.
Naming inputs or listing stages is identification, not an explanation of their
roles. Do not replace a requested explanation with a fact-list criterion.
For a novice request, require a short plain-language account of the essential
transformation, not merely its technical name; no unsolicited textbook detail.
Keep separate requested transformations as separate criteria. A supervision
yes/no question may use identification plus a requested limitation. Proposed
experiments use procedure for reproducible operations and explanation for
decision logic. Preserve brevity and do not invent extra user requirements.'''
