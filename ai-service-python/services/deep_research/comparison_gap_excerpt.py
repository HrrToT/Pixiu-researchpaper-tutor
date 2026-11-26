"""Keep whole-answer partial decisions actionable without trusting new facts."""

from copy import deepcopy


def guidance(check_id):
    return (f'\nFor whole-answer check {check_id}, if partial or missing, add missingRequestExcerpt '
            'to that check: copy one 8–120 character excerpt from the original user question '
            'that pinpoints the unmet clause. Omit this field if the gap cannot be localized. '
            'Do not add a new requirement, explain a paper fact, or weaken the whole-answer decision.\n')


def extract(rows, whole_question_id, question):
    """Remove the optional locator before normalizing the strict check schema."""
    if not isinstance(rows, list) or whole_question_id is None:
        return rows, None
    original = getattr(question, 'instruction_layers', (str(question),))[0]
    result = deepcopy(rows)
    excerpts = []
    for row in result:
        if not isinstance(row, dict) or row.get('obligationId') != whole_question_id:
            continue
        checks = row.get('checks')
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict) or check.get('checkId') != 'request':
                continue
            excerpt = check.pop('missingRequestExcerpt', None)
            if (check.get('status') in ('partial', 'missing') and isinstance(excerpt, str)
                    and excerpt == excerpt.strip() and 8 <= len(excerpt) <= 120
                    and excerpt != original.strip() and excerpt in original):
                excerpts.append(excerpt)
    return result, excerpts[0] if len(excerpts) == 1 else None
