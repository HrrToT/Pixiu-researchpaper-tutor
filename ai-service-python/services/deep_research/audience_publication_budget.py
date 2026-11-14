"""Reserve the actual publication layout before a reader wording edit."""
from copy import deepcopy
import json


def enabled(record, question):
    from services.deep_research.answer_constraints import requested_character_limit
    limit = requested_character_limit(question)
    return (type(record.get('audiencePublicationBudgetContractVersion')) is int
            and record['audiencePublicationBudgetContractVersion'] == 1
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion'] == 9
            and type(record.get('reportPresentationContractVersion')) is int
            and record['reportPresentationContractVersion'] in (2, 3, 4)
            and type(limit) is int and 0 < limit <= 700)


def allocation(report, evidence, question, context, protected_ids=()):
    from services.deep_research.answer_constraints import answer_character_count, requested_character_limit, visible_count
    if (not isinstance(context, dict) or set(context) != {'outputKind', 'presentationVersion'}
            or context['outputKind'] not in {'direction_survey', 'claim_verification', 'paper_comparison'}
            or type(context['presentationVersion']) is not int or context['presentationVersion'] not in (2, 3, 4)):
        raise ValueError('Invalid reader publication context')
    limit = requested_character_limit(question)
    if type(limit) is not int or not 0 < limit <= 700:
        raise ValueError('Reader publication budget requires a short explicit limit')
    claims = report.get('claims') if isinstance(report, dict) else None
    if (not isinstance(claims, list) or not claims
            or any(not isinstance(c, dict) or not isinstance(c.get('claimId'), str)
                   or not c['claimId'] or not isinstance(c.get('text'), str)
                   or not isinstance(c.get('conditions', {}), dict) for c in claims)):
        raise ValueError('Invalid reader publication draft')
    ids = [c['claimId'] for c in claims]
    if (len(set(ids)) != len(ids) or not isinstance(protected_ids, (list, tuple))
            or any(not isinstance(k, str) for k in protected_ids)
            or len(set(protected_ids)) != len(protected_ids) or not set(protected_ids) <= set(ids)):
        raise ValueError('Invalid reader publication targets')
    # Keep the actual section assignment, claim kinds and fixed objects. Only
    # editable prose is blanked; the same publication renderer counts labels.
    shadow = deepcopy(report)
    for claim in shadow['claims']:
        if claim['claimId'] not in protected_ids:
            claim.update(text='', conditions={})
    fixed = answer_character_count(shadow)
    reserved = visible_count(shadow, limit, context['outputKind'], evidence, context['presentationVersion'])
    return {'totalCharacters': limit, 'fixedCharacters': fixed,
            'layoutCharacters': max(0, reserved - fixed),
            'reservedCharacters': reserved, 'editableCharacters': max(0, limit - reserved),
            'protectedClaimIds': [k for k in ids if k in protected_ids],
            'editableClaimIds': [k for k in ids if k not in protected_ids]}


def prepare(request, report, evidence, question, context, protected_ids=(), *, protected_edits=False):
    budget = allocation(report, evidence, question, context, protected_ids)
    if not budget['editableCharacters']:
        return None, 'publication_budget_exhausted'
    request = deepcopy(request)
    if protected_edits:
        from services.deep_research.audience_edit_budget import allocation as original_allocation
        old = original_allocation(report, question, protected_ids)
        old_line = f"Total text+conditions of ONLY editable targets must fit {old['editableCharacters']} characters."
        new_line = f"Total text+conditions of ONLY editable targets must fit {budget['editableCharacters']} characters."
        old_json = json.dumps(old, ensure_ascii=False, separators=(',', ':'))
        revised = {**old, 'editableCharacters': budget['editableCharacters'], 'layoutCharacters': budget['layoutCharacters']}
        old_budget = 'Server-owned reader edit budget: ' + old_json
        if request['prompt'].count(old_budget) != 1:
            raise ValueError('Reader edit budget prompt mismatch')
        request['prompt'] = request['prompt'].replace(old_budget,
            'Server-owned reader edit budget: ' + json.dumps(revised, ensure_ascii=False, separators=(',', ':')), 1)
    else:
        old_line = f"Total ALL text+conditions character limit: {budget['totalCharacters']}."
        new_line = f"Total ALL editable text+conditions character limit: {budget['editableCharacters']}."
    if request['prompt'].count(old_line) != 1:
        raise ValueError('Reader character limit prompt mismatch')
    request['prompt'] = request['prompt'].replace(old_line, new_line, 1)
    request['prompt'] += '\nPublication layout budget (server-owned): ' + json.dumps(budget, ensure_ascii=False, separators=(',', ':')) + '''
The human limit includes fixed points AND visible publication labels/headings.
Their space is already reserved. Fit all editable text and conditions together
in editableCharacters. Keep required meanings and conditions; omit optional
algebra or repetition, never cut facts or add unsupported shortcuts. The server
will count the complete rendered answer again. This budget grants no factual approval.
'''
    from services.deep_research.audience_rewrite import MAX_INPUT_BYTES
    if len(request['prompt'].encode('utf8')) > MAX_INPUT_BYTES:
        return None, 'input_capacity'
    return request, None


def fits(report, evidence, question, context):
    from services.deep_research.answer_constraints import requested_character_limit, visible_count
    return visible_count(report, requested_character_limit(question), context['outputKind'],
                         evidence, context['presentationVersion']) <= requested_character_limit(question)
