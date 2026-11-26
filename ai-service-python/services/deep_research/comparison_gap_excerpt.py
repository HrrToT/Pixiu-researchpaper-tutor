"""Keep whole-answer partial decisions actionable without trusting new facts."""

from copy import deepcopy


def guidance(check_id, *, explain=False):
    text = (f'\nFor whole-answer check {check_id}, if partial or missing, add missingRequestExcerpt '
            'to that check: copy one 8–120 character excerpt from the original user question '
            'that pinpoints the unmet clause. Omit this field if the gap cannot be localized. '
            'Do not add a new requirement, explain a paper fact, or weaken the whole-answer decision.\n')
    if explain:
        text += ('If you provide missingRequestExcerpt, also provide missingAnswerElement: '
                 'one short sentence naming what the existing answer still fails to explain, '
                 'without repeating the request or prescribing a revision. If the answer already explains '
                 'that element across its accepted text and conditions, do not report that gap. '
                 'This is diagnostic only. Omit both fields on covered checks.\n')
    return text


def extract(rows, whole_question_id, question, *, explain=False):
    """Remove the optional locator before normalizing the strict check schema."""
    if not isinstance(rows, list) or whole_question_id is None:
        return rows, None, None
    original = getattr(question, 'instruction_layers', (str(question),))[0]
    result = deepcopy(rows)
    locations = []
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
            note = check.pop('missingAnswerElement', None) if explain else None
            if (check.get('status') in ('partial', 'missing') and isinstance(excerpt, str)
                    and excerpt == excerpt.strip() and 8 <= len(excerpt) <= 120
                    and excerpt != original.strip() and excerpt in original):
                note = note.strip() if isinstance(note, str) else ''
                if not (8 <= len(note) <= 180 and note != excerpt and '\n' not in note and '\r' not in note):
                    note = None
                locations.append((excerpt, note))
    excerpt, note = locations[0] if len(locations) == 1 else (None, None)
    return result, excerpt, note
