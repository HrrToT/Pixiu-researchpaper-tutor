"""Freeze requested answer requirements before synthesis; audit their bindings.

This is an identity/completeness contract, not a semantic proof. The reviewer
still has to judge whether an excerpt explains the requested relationship.
"""
import hashlib
import json
import re
from decimal import Decimal
from services.deep_research.answer_coverage import _bindings_supported, _known_claims_by_id

RESPONSE_TYPES = {'identification', 'explanation', 'procedure', 'limitation'}


def _numeric_identifiers(text):
    # Numbers explicitly being identified are answer objects, not evidence in
    # an expandable source block. Normalize notation, not units or rounding.
    return {Decimal(value) for value in re.findall(
        r'(?<![A-Za-z0-9_.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\d.])', text)}


def _identification_objects_present(criterion, obligation, bindings, *, format_limits=False):
    if criterion['responseType'] != 'identification':
        return True
    requested_text=str(obligation.get('requestExcerpt') or obligation.get('question') or '')
    requirement=criterion['requirement']
    if format_limits:
        from services.deep_research.joint_answer_bindings import without_character_limits
        requested_text=without_character_limits(requested_text);requirement=without_character_limits(requirement)
    requested = _numeric_identifiers(requested_text)
    objects = requested & _numeric_identifiers(requirement)
    displayed = _numeric_identifiers(' '.join(str(b.get('excerpt', '')) for b in bindings))
    return objects <= displayed


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


def completion_criteria_gaps(plan, claims, verdicts, *, display_metadata=None):
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
                        or not _criterion_bindings(found[0].get('bindings'),known,criterion,obligation,display_metadata)
                        or not _identification_objects_present(criterion, obligation, found[0]['bindings'],format_limits=isinstance(display_metadata,dict) and type(display_metadata.get('requestSemanticsContractVersion')) is int and display_metadata['requestSemanticsContractVersion']==2)):
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
    for row, claim in zip(answers, claims):
        if type(claim.get('protocolContractVersion')) is int and claim['protocolContractVersion'] == 2:
            row['protocolContractVersion'] = 2
            row['protocolExecutionSpec'] = claim.get('executionSpec')
        if type(claim.get('workflowContractVersion')) is int and claim['workflowContractVersion'] in (1, 2, 3, 4, 5):
            if claim['workflowContractVersion'] >= 2:
                row['workflowContractVersion'] = claim['workflowContractVersion']
            row['workflowExecutionSpec'] = claim.get('executionSpec')
    return hashlib.sha256(json.dumps([requirements, answers], ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def invalid_criterion_reviews(plan, claims, verdicts, *, display_metadata=None):
    """Separate an unreadable audit from a genuine reviewed content gap."""
    known = _known_claims_by_id(claims)
    invalid = []
    for item in plan:
        for obligation in item.get('obligations', []):
            criteria = obligation.get('completionCriteria')
            if criteria is None:
                continue
            identity = obligation['obligationId']
            matches = [v for v in verdicts if isinstance(v, dict) and v.get('obligationId') == identity]
            if len(matches) == 1 and matches[0].get('status') == 'not_required':
                continue  # Existing scope audit independently validates exemptions.
            rows = matches[0].get('criteria') if len(matches) == 1 else None
            valid = isinstance(rows, list) and len(rows) == len(criteria)
            for criterion in criteria:
                found = [r for r in rows if isinstance(r, dict) and r.get('criterionId') == criterion['criterionId']] if isinstance(rows, list) else []
                if len(found) != 1:
                    valid = False
                    continue
                row = found[0]
                bindings = row.get('bindings')
                status = row.get('status')
                if (row.get('responseType') != criterion['responseType']
                        or not isinstance(status, str) or status not in {'covered', 'partial', 'missing'}
                        or not isinstance(bindings, list)
                        or (status == 'covered' or bindings) and not _criterion_bindings(bindings,known,criterion,obligation,display_metadata)):
                    valid = False
            if not valid:
                invalid.append(identity)
    return invalid


def revalidate_completion_audit(plan, claims, audit, *, display_metadata=None):
    current = completion_contract_digest(plan, claims)
    if current is None:
        return audit
    missing = completion_criteria_gaps(plan, claims, audit.get('verdicts', []), **({'display_metadata':display_metadata} if display_metadata else {}))
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
question, state a neutral deliverable, never a guessed scientific answer. Do not
assume a particular mechanism, differentiability trick, uncertainty benefit,
numerical result or successful outcome before reading its evidence. Criteria
say what must be explained, not what the paper supposedly concludes.
When the user asks how training works, require the evidence-supported path from
model output through the training signal to parameter updates; if a step is
non-differentiable, ask how the authors handle it rather than assuming it is differentiable.
Use explanation criteria for the requested relationships: specify
which input acts on which operation/output and what the reader should understand.
Naming inputs or listing stages is identification, not an explanation of their
roles. Do not replace a requested explanation with a fact-list criterion.
For a novice request, require a short plain-language account of the essential
transformation, not merely its technical name; no unsolicited textbook detail.
Keep separate requested transformations as separate criteria. A supervision
yes/no question may use identification plus a requested limitation. Proposed
experiments use procedure for reproducible operations and explanation for
decision logic. Preserve brevity and do not invent extra user requirements.'''


def _criterion_bindings(bindings,known,criterion,obligation,metadata):
    if _bindings_supported(bindings,known):return True
    from services.deep_research.access_disclosure import access_only,access_bindings_supported
    return (criterion.get('responseType')=='identification' and access_only(obligation.get('question'))
        and access_bindings_supported(bindings,known,metadata,criterion.get('requirement')))
