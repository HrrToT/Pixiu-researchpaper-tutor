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
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion'] in (1,2)


def imperative_grounded(record):
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion']==2


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


_COMMAND = re.compile(r'^(?:(?:请你?|帮我|同时|并且?|然后|还要|再|只|仅|必须|需要)\s*|'
    r'(?:please|and|then|also|only)\s+)*(核查|核对|验证|判断|评估|评价|比较|对比|区分|解释|讲解|说明|'
    r'阐明|分析|设计|规划|给出|总结|概括|归纳|梳理|指出|'
    r'check\b|verify\b|assess\b|evaluate\b|compare\b|contrast\b|distinguish\b|explain\b|'
    r'describe\b|analy[sz]e\b|design\b|plan\b|summari[sz]e\b|identify\b)',re.I)
_LIMIT = re.compile(r'未验证|未核验|边界|限制|适用范围|推广范围|\b(?:unverified|limit\w*|boundar\w*)\b',re.I)
_PROCEDURE_COMMAND = re.compile(r'^(?:设计|规划|design|plan)$',re.I)


def _outside_examples(text):
    opens={'(':')','（':'）','[':']','【':'】','《':'》','“':'”','‘':'’','"':'"'}
    stack=[];visible=[]
    for char in text:
        if stack and char==stack[-1]:
            stack.pop();visible.append(' ')
        elif char in opens:
            stack.append(opens[char]);visible.append(' ')
        else: visible.append(' ' if stack else char)
    return ''.join(visible)


def _request_parts(text):
    """Literal command slices; commas inside a requested object list stay put.

    Only a new explicit command/question can start another aspect at a comma.
    Quoted examples and scientific hypotheses never become commands themselves.
    """
    opens={'(':')','（':'）','[':']','【':'】','《':'》','“':'”','‘':'’','"':'"'}
    stack=[];separators=[]
    for i,char in enumerate(text):
        if stack and char==stack[-1]: stack.pop()
        elif char in opens: stack.append(opens[char])
        elif not stack and char in '，,；;？?。\n': separators.append((i,char))
    def is_start(value):
        value=value.lstrip()
        return bool(_COMMAND.match(value) or re.match(r'^(?:如何|怎样|为什么|为何|什么|哪些|是否|能否|多少|何时|how\b|why\b|what\b|which\b|whether\b|when\b)',value,re.I))
    parts=[];start=0
    for index,char in separators:
        if char in '，,' and not is_start(text[index+1:]): continue
        parts.append(text[start:index].strip());start=index+1
    parts.append(text[start:].strip())
    return parts


def _requested_type(text):
    command=_COMMAND.match(text)
    if command:
        verb=command.group(1)
        if _PROCEDURE_COMMAND.fullmatch(verb) or verb=='给出' and re.search(r'实验|方案|对照|步骤|执行',text):
            return 'procedure'
        if _LIMIT.search(text) and re.fullmatch(r'区分|说明|指出|distinguish|describe|identify',verb,re.I):
            return 'limitation'
        return 'explanation'
    return 'explanation' if _EXPLAIN.search(text) else 'identification'


def normalize_generated_requirements(plan, question, *, literal_questions=False,literal_imperatives=False):
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
            parts = _request_parts(excerpt) if literal_imperatives else _question_parts(excerpt)
            if literal_imperatives:
                requests = [part for part in parts if _ASK.search(_outside_examples(part)) or _COMMAND.match(part)]
            else:
                requests = [part for part in parts if _ASK.search(part)]
            if not (1 if literal_questions else 2) <= len(requests) <= 4 or any(not 4 <= len(part) <= 500 for part in requests):
                continue
            obligation['completionCriteria'] = [
                {'criterionId': f'human_aspect_{i+1}', 'requirement': part,
                 'responseType': _requested_type(part) if literal_imperatives else
                     'explanation' if _EXPLAIN.search(part) else 'identification'}
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
