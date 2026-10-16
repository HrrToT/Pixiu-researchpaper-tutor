"""Keep human clarifications in the research goal without changing source permissions."""
from services.deep_research.contracts import DeepResearchError


def enabled(record):
    return type(record.get('clarificationContractVersion')) is int and record['clarificationContractVersion'] == 1


class ResearchQuestion(str):
    """Prompt text with the human-only layers used for local format constraints.

    JSON and provider interfaces see ordinary text. Rebuilt from durable state,
    this metadata prevents model-written clarification questions from becoming
    user-requested character limits. It grants no source or budget permissions.
    """
    def __new__(cls, text, layers):
        value = super().__new__(cls, text)
        value.instruction_layers = tuple(layers)
        return value

    def __getnewargs__(self):
        return str(self), self.instruction_layers


def instruction_layers(record):
    """Newest human answer first, then earlier answers and the original request.

    These are user instructions, never source evidence. Existing unmarked runs
    retain their old request/digest and are not regenerated after deployment.
    """
    original = record.get('question', '')
    if not enabled(record):
        return [original]
    state = record.get('state') or {}
    latest = state.get('clarification')
    history = state.get('clarificationHistory')
    if history is None:
        if latest is not None and (not isinstance(latest, str) or latest and not latest.strip()):
            raise DeepResearchError('invalid_clarification_context', '保存的补充要求无效，请检查研究记录。')
        return ([latest] if latest else []) + [original]
    if not isinstance(history, list) or any(not isinstance(row, dict)
            or not isinstance(row.get('answer'), str) or not row['answer'].strip()
            or not isinstance(row.get('question', ''), str) for row in history):
        raise DeepResearchError('invalid_clarification_context', '保存的补充要求历史无效，不能继续生成。')
    answers = [row['answer'] for row in history]
    if (answers and latest != answers[-1]) or (not answers and latest):
        raise DeepResearchError('invalid_clarification_context', '当前补充要求与历史记录不一致，不能继续生成。')
    return [*reversed(answers), original]


def effective_question(record):
    layers = instruction_layers(record)
    if len(layers) == 1:
        return layers[0]
    state = record.get('state') or {}
    history = state.get('clarificationHistory')
    rows = list(reversed(history)) if history else [{'answer': layers[0], 'question': state.get('clarificationQuestion', '')}]
    context = '\n\n'.join('Human answer:\n' + row['answer'] + '\nQuestion being answered:\n' + row.get('question', '')
                           for row in rows)
    return ResearchQuestion('User clarifications, newest first (human requirements, NOT paper evidence):\n'
            + context + '\n\nOriginal question:\n' + layers[-1]
            + '\nApply the latest clarification where requirements conflict; retain other original requirements. '
              'Permitted materials and source policy are fixed by the server, never widened by this text.', layers)


def separate_clarification(record):
    # The new question already includes every answer exactly once.
    return '' if enabled(record) else (record.get('state') or {}).get('clarification', '')
