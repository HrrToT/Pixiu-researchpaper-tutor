"""Separate explicit joined questions without inventing scientific requirements."""
import re

_EXPLANATORY=re.compile(r'为什么|为何|如何|怎样|怎么|\b(?:why|how)\b',re.I)
_QUESTION=re.compile(r'为什么|为何|如何|怎样|怎么|是否|能否|什么|哪些|多少|何时|\b(?:why|how|what|which|whether|when)\b',re.I)
_JOIN=re.compile(r'[,，、]\s*(?:以及|并且?|同时|and\b\s*)?|以及|并且|和|与|\band\b',re.I)
_NEGATIVE=re.compile(r'不(?:要|需|用|必|是)|无需|并非|并不|没有|未说明|\b(?:not|never|without|don\x27t)\b',re.I)

DRAFT_GUIDANCE='''For this bounded answer, use one allowed section unless the human
requests otherwise. Answer each literal question once, not repeated summaries
under different headings. Distinct why/how checks need both purpose and actual
operations toward the requested output. Never invent conditions to fill a heading.'''


def visible(text):
    from services.deep_research.evidence_requirements import _outside_examples
    result=_outside_examples(text)
    return re.sub(r'`+[^`]*`+|(?<!\w)\x27[^\x27\n]+\x27(?!\w)',lambda m:' '*len(m.group()),result)


def has_question(text):
    return bool(_QUESTION.search(visible(text)))


def explanatory(text):
    return bool(_EXPLANATORY.search(visible(text)))


def split_questions(text):
    from services.deep_research.evidence_requirements import _COMMAND
    masked=visible(text);command=_COMMAND.match(masked)
    first=_QUESTION.search(masked)
    if first is not None and _NEGATIVE.search(masked[:first.start()]):return [text]
    if command and not re.fullmatch(r'解释|讲解|说明|阐明|explain|describe',command.group(1),re.I):
        return [text]
    cuts=[];start=0
    for join in _JOIN.finditer(masked):
        if join.start()<start or not _QUESTION.search(masked[start:join.start()]):continue
        tail=masked[join.end():];query=_QUESTION.search(tail)
        if query is None or query.start()>24:continue
        prefix=tail[:query.start()]
        # Do not split the object list before the actual new question, or turn
        # quoted/negated commentary into another requested deliverable.
        if _JOIN.search(prefix) or re.search(r'[。！？;；\n]',prefix) or _NEGATIVE.search(prefix):continue
        cuts.append((join.start(),join.end()));start=join.end()
    parts=[];start=0
    for end,next_start in cuts:
        parts.append(text[start:end].strip());start=next_start
    parts.append(text[start:].strip())
    if not 2<=len(parts)<=4 or any(not 4<=len(part)<=500 or not has_question(part) for part in parts):
        return [text]
    return parts


def retain_unassigned_questions(plan, question):
    """Keep explicit joined asks that neither generated obligation actually anchors."""
    from copy import deepcopy
    from services.deep_research.evidence_requirements import _request_parts, _requested_type

    if type(question) is not str or len(plan) != 1:
        return plan, []
    item = plan[0]
    obligations = item['obligations']
    query = item.get('searchQuery')
    if (not query or not 1 <= len(obligations) <= 2
            or any(row.get('purpose') != 'answer_requirement' for row in obligations)):
        return plan, []
    # Standalone context and examples are excluded. Each group must contain
    # explicit joined questions, parsed from the literal human request.
    parts = []
    for clause in _request_parts(question):
        joined = split_questions(clause)
        if len(joined) > 1 and any(explanatory(part) for part in joined):
            parts.extend(joined)
    parts = list(dict.fromkeys(parts))
    if not 2 <= len(parts) <= 4:
        return plan, []
    anchored = [value for row in obligations for value in (
        row.get('requestExcerpt'), *(c['requirement'] for c in row.get('completionCriteria', [])))
        if isinstance(value, str) and len(value.strip()) >= 8]
    missing = [part for part in parts if not any(part in value or value in part for value in anchored)]
    if not missing or len(missing) == len(parts):
        return plan, []
    ids = {row['obligationId'] for row in obligations}
    obligation_id = 'remaining-request'
    while obligation_id in ids:
        obligation_id += '-part'
    result = deepcopy(plan)
    result[0]['obligations'].append({
        'obligationId': obligation_id,
        'question': '；'.join(missing),
        'requiredSources': [],  # The graph binds the same permitted task material.
        'searchQuery': query,
        'purpose': 'answer_requirement',
        'requestExcerpt': missing[0],
        'completionCriteria': [
            {'criterionId': f'human_aspect_{index}', 'requirement': part,
             'responseType': 'explanation' if explanatory(part) or part.startswith(('说清', '讲清'))
             else _requested_type(part)}
            for index, part in enumerate(missing, 1)
        ],
    })
    return result, [{'obligationId': obligation_id, 'change': 'retained_unassigned_human_aspects',
                     'criterionCount': len(missing)}]
