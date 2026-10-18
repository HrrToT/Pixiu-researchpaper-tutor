"""Keep generated requirements neutral and independently cover each requested aspect."""
from copy import deepcopy
import re

from services.deep_research.request_context import ResearchQuestion

_ASK = re.compile(r'如何|怎样|为什么|为何|什么|哪些|是否|能否|多少|何时|\b(?:how|why|what|which|whether|when)\b', re.I)
_EXPLAIN = re.compile(r'如何|怎样|为什么|为何|机制|原理|\b(?:how|why)\b', re.I)
_EXAMPLE = re.compile(r'[（(]\s*(?:例如|如|e\.g\.|such as)\s*[^（）()]*[）)]', re.I)


def enabled(record):
    return type(record.get('evidenceCoverageContractVersion')) is int and record['evidenceCoverageContractVersion'] in (1, 2, 3)


def grounded(record):
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion'] == 1


def criteria(obligation):
    return obligation.get('completionCriteria') or [{'criterionId': 'whole_obligation',
        'requirement': obligation['question'], 'responseType': 'explanation'}]


def _question_parts(text):
    # A comma inside a user-supplied example or a decimal point is not a new
    # requested aspect. Return literal slices, never paraphrase the request.
    opens = {'(': ')', '（': '）', '[': ']', '【': '】', '《': '》', '“': '”', '‘': '’'}
    stack, start, parts = [], 0, []
    for i, char in enumerate(text):
        if char in opens:
            stack.append(opens[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in '，,；;？?。\n':
            parts.append(text[start:i].strip()); start = i + 1
    parts.append(text[start:].strip())
    return parts


def normalize_generated_requirements(plan, question, *, literal_questions=False):
    """Change only the initial AI plan, never a saved human plan edit.

    Separate literal human questions when one generated criterion merged them.
    Candidate examples absent from human instructions are removed from generated
    questions/requirements, not treated as scientific answers. Other semantic
    additions remain subject to the original-question and factual audits.
    """
    human = question.instruction_layers if isinstance(question, ResearchQuestion) else (question,)
    result, changes = deepcopy(plan), []
    def neutral(text, identity, field):
        def replace(match):
            if any(match.group() in layer for layer in human):
                return match.group()
            changes.append({'obligationId': identity, 'field': field, 'change': 'removed_generated_example'})
            return ''
        return _EXAMPLE.sub(replace, text)
    for item in result:
        anchored = []
        for obligation in item['obligations']:
            oid = obligation['obligationId']
            obligation['question'] = neutral(obligation['question'], oid, 'question')
            original = obligation.get('completionCriteria', [])
            for criterion in original:
                criterion['requirement'] = neutral(criterion['requirement'], oid, 'requirement')
            excerpt = obligation.get('requestExcerpt', '')
            if not isinstance(excerpt, str) or not excerpt or not any(excerpt in layer for layer in human):
                continue
            parts = _question_parts(excerpt)
            requests = [part for part in parts if _ASK.search(part)]
            if not (1 if literal_questions else 2) <= len(requests) <= 4 or any(not 4 <= len(part) <= 500 for part in requests):
                continue
            obligation['completionCriteria'] = [
                {'criterionId': f'human_aspect_{i+1}', 'requirement': part,
                 'responseType': 'explanation' if _EXPLAIN.search(part) else 'identification'}
                for i, part in enumerate(requests)]
            if literal_questions:
                # The generated criterion can add an unprovided attribute list
                # even when the user asked one simple question. Use the literal
                # question, not a model paraphrase of the desired answer.
                obligation['question'] = excerpt
                anchored.append(excerpt)
            changes.append({'obligationId': oid, 'change': 'anchored_literal_human_aspects' if literal_questions else 'separated_literal_human_aspects',
                            'criterionCount': len(requests)})
        if literal_questions and len(anchored) == len(item['obligations']):
            item['question'] = '；'.join(dict.fromkeys(anchored))
    return result, changes
