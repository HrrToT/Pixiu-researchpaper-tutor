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
